<script setup lang="ts">
/**
 * The floor itself: a fixed-size canvas that scrolls, with every element placed on it.
 *
 * The canvas is authored at 1:1 and *displayed* through a CSS transform, which is the only
 * honest way to zoom a drag surface: the document keeps real canvas units, and the one
 * place that has to know about the scale is the pointer maths, which divides the screen
 * delta by it. Storing scaled coordinates instead would bake a rounding error into the
 * room every time someone zoomed.
 *
 * Pointer events rather than mouse events, so a trackpad, a mouse and a touch screen all go
 * down the same path. `setPointerCapture` is what makes a drag survive the pointer leaving
 * the shape — without it, a quick flick drops the table halfway.
 *
 * In preview mode the grid, the handles and the hit targets all go away: it is what the room
 * looks like, which is the thing worth checking before printing QR codes for it. Zoom stays,
 * because reading a plan is exactly when you want to see all of it at once.
 */
import { useElementSize } from '@vueuse/core'
import type { PlanElement } from '~/composables/useFloorPlan'
import { MIN_SIZE, clamp, snap } from '~/composables/useFloorPlan'

const props = defineProps<{
  elements: PlanElement[]
  width: number
  height: number
  selectedId: string | null
  /** Read-only: no dragging, no handles, no grid. */
  preview?: boolean
  /** Height cap for the scrolling frame; the zoom controls sit outside it. */
  frameClass?: string
  /**
   * What each table is doing right now, keyed by table id. Read only in preview: this is
   * what the POS paints the floor with, and the editor has no business showing it.
   */
  states?: Record<string, TableState>
  /** Preview only: tables become buttons and `pick` fires with the table's id. */
  pickable?: boolean
  /**
   * Scale the room to whatever box it is given, and never scroll. The POS floor: a till is
   * glanced at from across the room, and a room that has to be scrolled is a room with
   * tables nobody can see. Takes the zoom controls away, since the box decides.
   */
  fit?: boolean
}>()

const emit = defineEmits<{
  select: [id: string | null]
  place: [id: string, box: { x: number, y: number, width: number, height: number }]
  pick: [tableId: string]
}>()

/** Free, occupied, or waiting for the counter. */
export type TableState = 'free' | 'open' | 'billed'

/**
 * How a table reads on the POS floor. Fill, not just a border, because a server glances at
 * this from across the room and needs the room to look like the room.
 */
function stateClass(element: PlanElement): string {
  if (!props.pickable || element.kind !== 'table' || !element.tableId) {
    return ''
  }
  const state = props.states?.[element.tableId] ?? 'free'
  if (state === 'open') {
    return 'border-solid border-amber-500 bg-amber-100 text-amber-950 dark:bg-amber-500/25 dark:text-amber-100'
  }
  if (state === 'billed') {
    return 'border-solid border-sky-500 bg-sky-100 text-sky-950 dark:bg-sky-500/25 dark:text-sky-100'
  }
  return 'border-solid border-emerald-500/70 bg-emerald-50 dark:bg-emerald-500/15'
}

function pickLabel(element: PlanElement): string | undefined {
  if (!props.pickable || element.kind !== 'table' || !element.tableId) {
    return undefined
  }
  const state = props.states?.[element.tableId] ?? 'free'
  const said = { free: 'free', open: 'seated', billed: 'billed, awaiting payment' }[state]
  return `Table ${element.label}, ${said}`
}

function onPick(element: PlanElement): void {
  if (props.pickable && element.kind === 'table' && element.tableId) {
    emit('pick', element.tableId)
  }
}

/** Fixed stops rather than a free ratio: every one of them renders the grid crisply. */
const ZOOMS = [0.4, 0.5, 0.6, 0.75, 1, 1.25, 1.5] as const
const DEFAULT_ZOOM = ZOOMS.indexOf(1)

const step = ref(DEFAULT_ZOOM)

/** The box the room is shown in; only measured when fitting to it. */
const frame = ref<HTMLElement | null>(null)
const { width: frameWidth, height: frameHeight } = useElementSize(frame)

/** Fitting: the largest scale at which the whole room, plus a little air, is inside the box. */
const FIT_PADDING = 16
const FIT_MAX = 2.5

const scale = computed(() => {
  if (!props.fit) {
    return ZOOMS[step.value] ?? 1
  }
  if (!frameWidth.value || !frameHeight.value) {
    return 1
  }
  return Math.min(
    (frameWidth.value - FIT_PADDING) / props.width,
    (frameHeight.value - FIT_PADDING) / props.height,
    FIT_MAX,
  )
})

function zoom(by: number): void {
  step.value = clamp(step.value + by, 0, ZOOMS.length - 1)
}

/** What is being dragged, and where the pointer was when it started. */
interface Gesture {
  id: string
  mode: 'move' | 'resize'
  pointerX: number
  pointerY: number
  origin: { x: number, y: number, width: number, height: number }
}

const gesture = ref<Gesture | null>(null)

function begin(event: PointerEvent, element: PlanElement, mode: Gesture['mode']): void {
  if (props.preview) {
    return
  }
  event.preventDefault()
  emit('select', element.id)
  gesture.value = {
    id: element.id,
    mode,
    pointerX: event.clientX,
    pointerY: event.clientY,
    origin: { x: element.x, y: element.y, width: element.width, height: element.height },
  }
  ;(event.currentTarget as HTMLElement).setPointerCapture(event.pointerId)
}

function move(event: PointerEvent): void {
  const active = gesture.value
  if (!active) {
    return
  }
  // Screen pixels back into canvas units: at 50% zoom a 10px drag is 20 units of floor.
  const dx = (event.clientX - active.pointerX) / scale.value
  const dy = (event.clientY - active.pointerY) / scale.value
  const { x, y, width, height } = active.origin
  if (active.mode === 'move') {
    emit('place', active.id, { x: snap(x + dx), y: snap(y + dy), width, height })
    return
  }
  emit('place', active.id, {
    x,
    y,
    width: clamp(snap(width + dx), MIN_SIZE, props.width - x),
    height: clamp(snap(height + dy), MIN_SIZE, props.height - y),
  })
}

function end(): void {
  gesture.value = null
}

/** The box, in the units the canvas is drawn in. */
function box(element: PlanElement): Record<string, string> {
  return {
    left: `${element.x}px`,
    top: `${element.y}px`,
    width: `${element.width}px`,
    height: `${element.height}px`,
  }
}

/** Shape is purely visual, so it is purely a class list. */
function shapeClass(element: PlanElement): string {
  if (element.kind !== 'table') {
    return 'rounded-sm'
  }
  if (element.shape === 'circle') {
    return 'rounded-full'
  }
  if (element.shape === 'diamond') {
    return 'rotate-45 rounded-md'
  }
  return 'rounded-lg'
}
</script>

<template>
  <!-- `min-w-0`: this is a grid item next to the editor's panel, and the automatic minimum
       size of a grid item is its content unless the item is itself a scroll container. The
       scroll container is now one level down (the zoom controls have to sit outside it), so
       without this the 1200-unit room blows the column out and the dialog scrolls sideways. -->
  <div class="relative min-w-0" :class="fit ? 'flex min-h-0 flex-col' : ''">
    <!-- The canvas is wider than the panel it sits in; it scrolls in its own box rather
         than making the settings page scroll sideways. Fitting, the box is the size it
         was given and the room is scaled into the middle of it. -->
    <div
      ref="frame"
      class="rounded-xl border border-border bg-muted/20"
      :class="[fit ? 'grid min-h-0 flex-1 place-items-center overflow-hidden' : 'overflow-auto', frameClass]"
    >
      <!-- Two boxes: the outer one reserves the *scaled* footprint so scrollbars stay
           honest, the inner one is the room at its authored size, drawn through the
           transform. -->
      <div :style="{ width: `${width * scale}px`, height: `${height * scale}px` }">
        <div
          class="relative origin-top-left select-none"
          :class="preview ? '' : 'bg-[length:20px_20px] bg-[radial-gradient(var(--color-border)_1px,transparent_1px)]'"
          :style="{
            width: `${width}px`,
            height: `${height}px`,
            transform: `scale(${scale})`,
          }"
          @pointerdown.self="emit('select', null)"
        >
          <div
            v-for="element in elements"
            :key="element.id"
            class="absolute"
            :style="box(element)"
          >
            <!-- One positioned wrapper per element, so the diamond's rotation applies to
                 the shape and never to the label inside it. -->
            <div
              class="grid h-full w-full place-items-center border-2 text-center transition-colors"
              :class="[
                shapeClass(element),
                preview ? '' : 'cursor-move',
                pickable && element.kind === 'table' ? 'cursor-pointer hover:brightness-95' : '',
                element.id === selectedId && !preview
                  ? 'border-primary bg-primary/10'
                  : element.kind === 'wall'
                    ? 'border-transparent bg-muted-foreground/25'
                    : element.kind === 'text'
                      ? 'border-transparent bg-transparent'
                      // On the POS floor the state paints the table. The editor's dashed
                      // outline must not be emitted alongside it: two competing border and
                      // background utilities resolve by stylesheet order, not by which one
                      // this list puts last.
                      : stateClass(element) || 'border-dashed border-muted-foreground/50 bg-background',
              ]"
              :role="pickable && element.kind === 'table' ? 'button' : undefined"
              :aria-label="pickLabel(element)"
              :tabindex="pickable && element.kind === 'table' ? 0 : undefined"
              @click="onPick(element)"
              @keydown.enter="onPick(element)"
              @pointerdown="begin($event, element, 'move')"
              @pointermove="move"
              @pointerup="end"
              @pointercancel="end"
            >
              <span
                v-if="element.kind === 'table'"
                class="pointer-events-none px-1 text-sm font-medium tracking-tight break-all"
                :class="element.shape === 'diamond' ? '-rotate-45' : ''"
              >{{ element.label }}</span>
              <span
                v-else-if="element.kind === 'text'"
                class="pointer-events-none px-1 text-sm text-muted-foreground"
              >{{ element.text }}</span>
            </div>

            <!-- Resize grip. Outside the rotated shape, so it stays at the bottom right of
                 the box a person can actually see. -->
            <!-- Counter-scaled: the grip lives inside the zoomed layer, so at 40% it would
                 render as a 6px target nobody can hit. The room shrinks; the handle does not. -->
            <button
              v-if="element.id === selectedId && !preview"
              type="button"
              :aria-label="`Resize ${element.label || element.text || 'element'}`"
              class="absolute -right-1.5 -bottom-1.5 size-3.5 cursor-nwse-resize rounded-sm border border-background bg-primary"
              :style="{ transform: `scale(${1 / scale})` }"
              @pointerdown="begin($event, element, 'resize')"
              @pointermove="move"
              @pointerup="end"
              @pointercancel="end"
            />
          </div>

          <p
            v-if="!elements.length"
            class="pointer-events-none absolute inset-0 grid place-items-center px-6 text-center text-sm text-muted-foreground"
          >
            Nothing on the floor yet. Add a table from the panel on the left.
          </p>
        </div>
      </div>
    </div>

    <!-- Zoom. Outside the scrolling box so it stays put while the room moves under it. -->
    <div
      v-if="!fit"
      class="absolute right-3 bottom-3 flex items-center gap-0.5 rounded-lg border border-border bg-background/90 p-1 shadow-xs backdrop-blur-sm"
    >
      <Button
        variant="ghost"
        size="icon-sm"
        aria-label="Zoom out"
        :disabled="step === 0"
        @click="zoom(-1)"
      >
        <FontAwesomeIcon :icon="['fas', 'minus']" />
      </Button>
      <button
        type="button"
        class="min-w-12 rounded-md px-1 py-1 text-xs tabular-nums transition-colors outline-hidden hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring"
        title="Reset zoom"
        @click="step = DEFAULT_ZOOM"
      >
        {{ Math.round(scale * 100) }}%
      </button>
      <Button
        variant="ghost"
        size="icon-sm"
        aria-label="Zoom in"
        :disabled="step === ZOOMS.length - 1"
        @click="zoom(1)"
      >
        <FontAwesomeIcon :icon="['fas', 'plus']" />
      </Button>
    </div>
  </div>
</template>
