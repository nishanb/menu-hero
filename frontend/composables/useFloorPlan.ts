/**
 * One restaurant's floor: the saved plan, and the working copy the editor drags around.
 *
 * Two copies, deliberately. `saved`/`savedElements` is what the server last agreed and is
 * what the settings page shows; `elements` is the buffer the modal edits. Nothing reaches
 * the backend until Save, which writes the whole plan in one `PUT`, and Discard rebuilds
 * the buffer from the saved copy without a round trip. That is why there are no per-element
 * requests here — a half-saved room has no meaning, and dragging a table would otherwise be
 * a request per frame.
 *
 * Two things are being edited at once, and the split matters:
 *
 * - the **drawing** — where each thing sits, how big it is, what shape it is drawn as. It is
 *   replaced outright on every save.
 * - the **tables** — the name and seat count of anything a diner can order from. Those are
 *   rows in the database that outlive the drawing, because an order points at one and a QR
 *   code encodes one. The editor only ever sends a table's *name*; the server decides
 *   whether that is a new table or one coming back onto the floor.
 *
 * Coordinates are canvas units with the origin at the top left, and are never scaled here:
 * the canvas scrolls rather than zooms, so what is dragged is what is stored.
 */
import type { Ref } from 'vue'
import type {
  ElementKind,
  ElementShape,
  FloorPlan,
  FloorPlanElementSave,
  FloorPlanSave,
} from '~/types/api'
import { toApiError } from '~/utils/api-error'

/** One element while it is being edited. Tables carry their name; the server resolves ids. */
export interface PlanElement {
  id: string
  kind: ElementKind
  shape: ElementShape
  /** Known only for a table that has been saved before; absent for one just drawn. */
  tableId: string | null
  label: string
  seats: number
  text: string
  x: number
  y: number
  width: number
  height: number
  rotation: number
}

/** Movement and resizing snap to this, which is what keeps a hand-dragged room tidy. */
export const GRID = 10

/**
 * Smallest an element can be dragged to. Stricter than the backend's `MIN_ELEMENT_SIZE`
 * (16), on purpose: a 16-unit table is a dot nobody can grab again.
 */
export const MIN_SIZE = 20

/** What each kind of new element starts out as. */
const TEMPLATES: Record<string, { width: number, height: number }> = {
  circle: { width: 90, height: 90 },
  square: { width: 90, height: 90 },
  diamond: { width: 90, height: 90 },
  rectangle: { width: 150, height: 90 },
  wall: { width: 220, height: 30 },
  text: { width: 160, height: 34 },
}

const LETTERS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'

export function useFloorPlan(tenantId: Ref<string | undefined>) {
  const api = useRestaurantApi()

  const width = ref(1200)
  const height = ref(800)
  const elements = ref<PlanElement[]>([])
  const selectedId = ref<string | null>(null)

  const loading = ref(true)
  const saving = ref(false)
  const error = ref('')

  /**
   * The plan as the server last agreed it. Kept apart from the editable copy on purpose:
   * the settings page shows this one, the dialog edits the other. Someone who opens the
   * editor, moves three tables and closes it without saving has not changed the restaurant,
   * and the page behind must not pretend otherwise.
   */
  const server = ref<FloorPlan | null>(null)
  /** Serialised `server`; what dirty compares against. */
  const baseline = ref('')

  const selected = computed(() => elements.value.find(item => item.id === selectedId.value) ?? null)

  /**
   * What is stopping this plan being saved, in the owner's terms, or `''`.
   *
   * The backend refuses a nameless table and an empty caption, and rightly - a table with
   * no name is not orderable. But it refuses them as a 422 about an element id, which says
   * nothing to the person who just cleared a field. Catching it here turns that into a
   * sentence next to a disabled button.
   */
  const problem = computed(() => {
    if (elements.value.some(item => item.kind === 'table' && !item.label.trim())) {
      return 'Every table needs a name.'
    }
    if (elements.value.some(item => item.kind === 'text' && !item.text.trim())) {
      return 'A text label cannot be empty.'
    }
    const names = tables.value.map(item => item.label.trim().toLowerCase())
    if (new Set(names).size !== names.length) {
      return 'Two tables have the same name. Give each one its own.'
    }
    return ''
  })
  const tables = computed(() => elements.value.filter(item => item.kind === 'table'))
  const dirty = computed(() => snapshot() !== baseline.value)

  function snapshot(): string {
    return JSON.stringify(elements.value)
  }

  /** Take the server's answer as the truth, and start a fresh working copy from it. */
  function adopt(plan: FloorPlan): void {
    server.value = plan
    reset()
  }

  /**
   * Throw the working copy away and rebuild it from `server`.
   *
   * No round trip: the answer is already in hand, and re-fetching would make Discard feel
   * like a save. Folds the plan and its tables back into one list — the drawing knows a
   * `table_id`, the name and seat count live on the table.
   */
  function reset(): void {
    const plan = server.value
    width.value = plan?.width ?? 1200
    height.value = plan?.height ?? 800
    elements.value = plan ? toElements(plan) : []
    selectedId.value = null
    baseline.value = snapshot()
  }

  async function load(): Promise<void> {
    const id = tenantId.value
    if (!id) {
      loading.value = false
      return
    }
    loading.value = true
    error.value = ''
    try {
      adopt(await api.floorPlan(id))
    }
    catch (cause) {
      error.value = toApiError(cause).detail
    }
    finally {
      loading.value = false
    }
  }

  async function save(): Promise<boolean> {
    const id = tenantId.value
    if (!id) {
      return false
    }
    saving.value = true
    error.value = ''
    try {
      adopt(await api.saveFloorPlan(id, payload()))
      return true
    }
    catch (cause) {
      error.value = toApiError(cause).detail
      return false
    }
    finally {
      saving.value = false
    }
  }

  /**
   * The body of the `PUT`.
   *
   * A table sends `label` and `seats` and, when it has one, the id it already had — that id
   * is what stops a rename from looking like a different table and orphaning its QR code.
   * Everything else sends neither: the backend refuses a caption that claims a seat count.
   */
  function payload(): FloorPlanSave {
    return {
      width: width.value,
      height: height.value,
      elements: elements.value.map((element) => {
        const base: FloorPlanElementSave = {
          id: element.id,
          kind: element.kind,
          shape: element.shape,
          x: round(element.x),
          y: round(element.y),
          width: round(element.width),
          height: round(element.height),
          rotation: element.rotation,
        }
        if (element.kind === 'table') {
          base.label = element.label.trim()
          base.seats = element.seats
          if (element.tableId) {
            base.table_id = element.tableId
          }
        }
        else {
          base.text = element.text
        }
        return base
      }),
    }
  }

  // ------------------------------------------------------------------ editing

  function add(kind: ElementKind, shape: ElementShape = 'rectangle'): PlanElement {
    const size = TEMPLATES[kind === 'table' ? shape : kind] ?? TEMPLATES.rectangle!
    const element: PlanElement = {
      id: newId(),
      kind,
      shape: kind === 'table' ? shape : 'rectangle',
      tableId: null,
      label: kind === 'table' ? nextLabel() : '',
      seats: kind === 'table' ? 4 : 0,
      text: kind === 'text' ? 'Text' : '',
      ...freeSpot(size.width, size.height),
      width: size.width,
      height: size.height,
      rotation: 0,
    }
    elements.value = [...elements.value, element]
    selectedId.value = element.id
    return element
  }

  function update(id: string, changes: Partial<PlanElement>): void {
    elements.value = elements.value.map(item => (item.id === id ? { ...item, ...changes } : item))
  }

  /** Move and resize in one call, clamped so nothing can be dragged off the floor. */
  function place(id: string, box: { x: number, y: number, width: number, height: number }): void {
    const w = clamp(box.width, MIN_SIZE, width.value)
    const h = clamp(box.height, MIN_SIZE, height.value)
    update(id, {
      width: w,
      height: h,
      x: clamp(box.x, 0, width.value - w),
      y: clamp(box.y, 0, height.value - h),
    })
  }

  function remove(id: string): void {
    elements.value = elements.value.filter(item => item.id !== id)
    if (selectedId.value === id) {
      selectedId.value = null
    }
  }

  function discard(): void {
    error.value = ''
    reset()
  }

  /**
   * `A1`, `A2`, … `B1`: the first name nothing is using.
   *
   * Auto-named because a table has to have a name to be saved at all, and being made to type
   * one before the shape has even landed is the wrong order. It is editable straight after.
   */
  function nextLabel(): string {
    const taken = new Set(tables.value.map(table => table.label.trim().toLowerCase()))
    for (const letter of LETTERS) {
      for (let number = 1; number <= 20; number += 1) {
        const candidate = `${letter}${number}`
        if (!taken.has(candidate.toLowerCase())) {
          return candidate
        }
      }
    }
    return `T${taken.size + 1}`
  }

  /**
   * The first free spot on the floor, scanning left to right and top to bottom.
   *
   * A cascade of fixed offsets is the obvious thing and the wrong one: shapes land on top
   * of each other, and the name written in the middle of a table disappears under the next
   * one before it has been read. This keeps a gap between everything it places.
   */
  function freeSpot(w: number, h: number): { x: number, y: number } {
    const gap = GRID * 2
    for (let y = GRID * 4; y + h <= height.value; y += gap) {
      for (let x = GRID * 4; x + w <= width.value; x += gap) {
        const spot = { x, y, width: w, height: h }
        if (!elements.value.some(item => overlaps(item, spot, gap))) {
          return { x, y }
        }
      }
    }
    // A full floor: drop it on the near corner rather than refusing to add anything.
    return { x: GRID * 4, y: GRID * 4 }
  }

  watch(tenantId, () => void load(), { immediate: true })

  /** The saved plan, ready to render read-only. Empty until the first load answers. */
  const savedElements = computed(() => (server.value ? toElements(server.value) : []))

  return {
    width,
    height,
    elements,
    savedElements,
    /** The saved plan itself, for anything that needs its name or its tables. */
    saved: server,
    tables,
    selectedId,
    selected,
    loading,
    saving,
    error,
    dirty,
    /** Non-empty while the plan cannot be saved; shown next to a disabled Save. */
    problem,
    load,
    save,
    discard,
    add,
    update,
    place,
    remove,
  }
}

/**
 * Fold a plan and its tables into one list.
 *
 * The two halves are stored apart because a table outlives the drawing (see the module
 * docstring), but nothing that *renders* wants them apart: a shape on the floor has to know
 * the name written in the middle of it.
 */
function toElements(plan: FloorPlan): PlanElement[] {
  const byId = new Map(plan.tables.map(table => [table.id, table]))
  return plan.elements.map((element) => {
    const table = element.table_id ? byId.get(element.table_id) : undefined
    return {
      id: element.id,
      kind: element.kind,
      shape: element.shape,
      tableId: element.table_id,
      label: table?.label ?? '',
      seats: table?.seats ?? 0,
      text: element.text,
      x: element.x,
      y: element.y,
      width: element.width,
      height: element.height,
      rotation: element.rotation,
    }
  })
}

/**
 * The working copy plus everything that acts on it.
 *
 * Named so the panel that owns it can hand it to the dialog that edits it: one buffer, two
 * components, and closing the dialog therefore cannot lose anything.
 */
export type FloorPlanStore = ReturnType<typeof useFloorPlan>

/** Snap a canvas coordinate to the grid. */
export function snap(value: number): number {
  return Math.round(value / GRID) * GRID
}

export function clamp(value: number, low: number, high: number): number {
  return Math.min(Math.max(value, low), Math.max(low, high))
}

/** True when two boxes touch, with ``gap`` units of breathing room around each. */
function overlaps(
  a: { x: number, y: number, width: number, height: number },
  b: { x: number, y: number, width: number, height: number },
  gap: number,
): boolean {
  return (
    a.x < b.x + b.width + gap
    && a.x + a.width + gap > b.x
    && a.y < b.y + b.height + gap
    && a.y + a.height + gap > b.y
  )
}

function round(value: number): number {
  return Math.round(value * 100) / 100
}

/**
 * A stable id for an element, generated here rather than by the server.
 *
 * The editor has to be able to talk about a shape that has never been saved — select it,
 * drag it, delete it — so ids cannot wait for a round trip. `randomUUID` needs a secure
 * context; the fallback keeps a plain-HTTP dev server working.
 */
function newId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  return `el-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
}
