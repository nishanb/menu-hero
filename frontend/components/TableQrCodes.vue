<script setup lang="ts">
/**
 * QR codes for the tables on the floor plan, ready to print.
 *
 * **What the code encodes is the table, not a session.** A printed sticker outlives any
 * number of seatings, so it points at a stable table URL and the server mints the short-lived
 * table token when a diner actually arrives (HLD 3.4). That is the whole reason a table is an
 * identity that survives the floor plan being redrawn — see `backend/app/models/table.py`.
 * Encoding a token here would mean reprinting every code every service.
 *
 * The codes are drawn as **SVG**, not canvas. A canvas QR is a bitmap: enlarge it for an A5
 * tent card and the modules go soft, and a printer at 600 dpi has nothing extra to work with.
 * SVG prints at the device's own resolution however big the card is.
 */
import QRCode from 'qrcode'
import type { FloorPlan, RestaurantTable } from '~/types/api'
import { toApiError } from '~/utils/api-error'

const props = defineProps<{ tenantId: string }>()

const api = useRestaurantApi()
const { active } = useRestaurants()
const origin = useRequestURL().origin

const plan = ref<FloorPlan | null>(null)
/** The full record, for the logo. The switcher's summary omits it on purpose. */
const restaurant = computed(() => active.value?.detail)
const loading = ref(true)
const error = ref('')

/** Four ways a QR code ends up in front of a diner. */
const DESIGNS = [
  {
    value: 'showcase',
    label: 'Showcase',
    blurb: 'A full card on a colour ground. The one that stands on the table and gets read.',
  },
  {
    value: 'card',
    label: 'Card',
    blurb: 'A rounded card with a header bar. The one to stand on a table.',
  },
  {
    value: 'tent',
    label: 'Table tent',
    blurb: 'Two halves, one inverted. Fold it and it reads from both sides.',
  },
  {
    value: 'badge',
    label: 'Badge',
    blurb: 'A circular sticker. For the edge of a table or a laminate.',
  },
  {
    value: 'plain',
    label: 'Plain',
    blurb: 'Code and label, nothing else. Cheapest to print, easiest to cut.',
  },
] as const

type Design = (typeof DESIGNS)[number]['value']

/**
 * Curated grounds rather than a colour picker.
 *
 * A picker produces combinations nobody would choose on purpose, and these have to survive
 * being printed flat on card. Each pair is a deep ground with one warm accent, which is what
 * the references all do: the ground carries the card, the accent carries the call to action.
 */
const THEMES = [
  { value: 'ink', label: 'Ink', ground: '#14110f', accent: '#e0a458', ink: '#faf7ef' },
  { value: 'forest', label: 'Forest', ground: '#14342a', accent: '#e8722c', ink: '#f2f6f2' },
  { value: 'terracotta', label: 'Terracotta', ground: '#8a4a2b', accent: '#f2c14e', ink: '#fdf6ef' },
  { value: 'wine', label: 'Wine', ground: '#4a1220', accent: '#d9a566', ink: '#fbf3f0' },
  { value: 'slate', label: 'Slate', ground: '#1e293b', accent: '#38bdf8', ink: '#f1f5f9' },
] as const

type Theme = (typeof THEMES)[number]['value']

const SIZES = [
  { value: 'small', label: 'Small', mm: 32, perRow: 4, showcasePerRow: 3 },
  { value: 'medium', label: 'Medium', mm: 48, perRow: 3, showcasePerRow: 2 },
  { value: 'large', label: 'Large', mm: 72, perRow: 2, showcasePerRow: 1 },
] as const

type Size = (typeof SIZES)[number]['value']

const design = ref<Design>('showcase')
const theme = ref<Theme>('ink')
const size = ref<Size>('medium')
/** The line above the call to action. Optional; most cards read better without one. */
const message = ref('')
const showDoor = ref(true)
/** Dashed guides around each card. Wanted when cutting, in the way when not. */
const showCutMarks = ref(true)
const chosen = ref<Set<string>>(new Set())

const sizing = computed(() => SIZES.find(entry => entry.value === size.value) ?? SIZES[1])

const showcase = computed(() => design.value === 'showcase')

const palette = computed(() => THEMES.find(entry => entry.value === theme.value) ?? THEMES[0])

const perRow = computed(() => geometry.value.perRow)

/** What a diner is told to do, in three steps, on the strip at the foot of the card. */
// Three of similar length, so the strip sets as three even columns rather than one that
// wraps and drags the row out of line.
const STEPS = ['Scan the code', 'Browse the menu', 'Order at the table']

/* ------------------------------------------------------------------ the page */

const PAGE = { width: 210, height: 297, margin: 12, gutter: 6 }
/** Millimetres of paper a card can actually use. */
const printable = computed(() => ({
  width: PAGE.width - PAGE.margin * 2,
  height: PAGE.height - PAGE.margin * 2,
}))

/** How many cards of a given size actually land on one sheet, and how they sit. */
function geometryFor(entry: (typeof SIZES)[number]): {
  perRow: number
  width: number
  height: number
  perPage: number
} {
  const columns = showcase.value ? entry.showcasePerRow : entry.perRow
  const width = (printable.value.width - PAGE.gutter * (columns - 1)) / columns
  const height = showcase.value
    ? width * (4 / 3)
    : design.value === 'tent'
      ? entry.mm * 2 + 30
      : design.value === 'badge'
        ? width
        : entry.mm + (design.value === 'card' ? 26 : 14)
  const rows = Math.max(
    1,
    Math.floor((printable.value.height + PAGE.gutter) / (height + PAGE.gutter)),
  )
  return { perRow: columns, width, height, perPage: rows * columns }
}

const geometry = computed(() => geometryFor(sizing.value))

const cardWidth = computed(() => geometry.value.width)

const perPage = computed(() => geometry.value.perPage)

/**
 * The cards, cut into pages.
 *
 * Paginated here rather than left to the print engine because the preview has to *show* the
 * pages: a continuous strip hides the one thing worth checking before printing 40 stickers,
 * which is whether a card lands half on one sheet and half on the next.
 */
const pages = computed(() => {
  const size = perPage.value
  const out: Card[][] = []
  for (let at = 0; at < cards.value.length; at += size) {
    out.push(cards.value.slice(at, at + size))
  }
  return out
})

/**
 * No `@page` margin: the page boxes below are drawn at a full 210 x 297mm and carry the
 * 12mm margin as their own padding, so the browser adding another one would shrink every
 * sheet and throw the cut marks out.
 */
useHead({
  style: [{ innerHTML: '@page { size: A4; margin: 0; }' }],
})

/* ------------------------------------------------------------------ what gets a code */

const tables = computed(() => plan.value?.tables ?? [])

/**
 * One card per selected table, plus the door code.
 *
 * The door code carries the restaurant rather than a table — somebody reading a menu at the
 * counter has not sat down anywhere, and giving them table A1's code would seat them at it.
 */
interface Card {
  key: string
  label: string
  caption: string
  url: string
}

const cards = computed<Card[]>(() => {
  const list: Card[] = tables.value
    .filter(table => chosen.value.has(table.id))
    .map(table => ({
      key: table.id,
      label: table.label,
      caption: table.seats ? `${table.seats} seats` : 'Table',
      url: `${origin}/restaurant/${active.value?.id}/order?table=${table.id}`,
    }))
  if (showDoor.value && active.value) {
    list.unshift({
      key: 'door',
      label: 'Menu',
      caption: 'At the door',
      url: `${origin}/restaurant/${active.value.id}/order`,
    })
  }
  return list
})

/* ------------------------------------------------------------------ drawing them */

const svgByKey = ref<Record<string, string>>({})

/**
 * Redrawn whenever the set of cards changes.
 *
 * `margin: 0` because the card supplies its own quiet zone as padding — the library's own
 * margin is measured in modules, so it grows with the code and throws the layout out.
 * Error correction M: enough to survive a scuffed sticker without inflating the module count.
 */
watch(
  cards,
  async (list) => {
    const drawn: Record<string, string> = {}
    await Promise.all(
      list.map(async (card) => {
        drawn[card.key] = await QRCode.toString(card.url, {
          type: 'svg',
          margin: 0,
          errorCorrectionLevel: 'M',
          color: { dark: '#000000', light: '#00000000' },
        })
      }),
    )
    svgByKey.value = drawn
  },
  { immediate: true },
)

/* ------------------------------------------------------------------ selection */

function toggle(id: string): void {
  const next = new Set(chosen.value)
  if (next.has(id)) {
    next.delete(id)
  }
  else {
    next.add(id)
  }
  chosen.value = next
}

function selectAll(): void {
  chosen.value = new Set(tables.value.map(table => table.id))
}

function print(): void {
  window.print()
}

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    plan.value = await api.floorPlan(props.tenantId)
    selectAll()
  }
  catch (cause) {
    error.value = toApiError(cause).detail
  }
  finally {
    loading.value = false
  }
}

watch(() => props.tenantId, load, { immediate: true })
</script>

<template>
  <div class="grid gap-5">
    <Alert v-if="error" variant="destructive">
      <FontAwesomeIcon :icon="['fas', 'circle-exclamation']" />
      <AlertTitle>That did not go through</AlertTitle>
      <AlertDescription>{{ error }}</AlertDescription>
    </Alert>

    <div v-if="loading" class="grid gap-2">
      <Skeleton class="h-24 w-full" />
      <Skeleton class="h-72 w-full" />
    </div>

    <section
      v-else-if="!tables.length"
      class="rounded-xl border border-dashed border-border px-6 py-12 text-center"
    >
      <p class="text-sm text-muted-foreground">
        There are no tables yet. They come from the floor plan — draw the room and every table
        on it gets a code that keeps working when the room is rearranged.
      </p>
      <Button class="mt-4" size="sm" as-child>
        <NuxtLink to="/settings?tab=floor-plan">Draw the floor plan</NuxtLink>
      </Button>
    </section>

    <template v-else>
      <!-- Controls ---------------------------------------------------------- -->
      <div class="grid gap-4 rounded-xl border border-border bg-card p-4 print:hidden">
        <div class="grid gap-2">
          <p class="text-xs font-medium text-muted-foreground uppercase">Design</p>
          <div class="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
            <button
              v-for="option in DESIGNS"
              :key="option.value"
              type="button"
              :aria-pressed="design === option.value"
              class="rounded-lg border px-3 py-2.5 text-left transition-colors outline-hidden focus-visible:ring-2 focus-visible:ring-ring"
              :class="design === option.value
                ? 'border-primary bg-accent'
                : 'border-border hover:bg-accent/60'"
              @click="design = option.value"
            >
              <span class="text-sm font-medium">{{ option.label }}</span>
              <span class="mt-0.5 block text-xs leading-snug text-muted-foreground">
                {{ option.blurb }}
              </span>
            </button>
          </div>
        </div>

        <div v-if="showcase" class="grid gap-3 sm:grid-cols-[auto_1fr] sm:items-end">
          <div class="grid gap-2">
            <p class="text-xs font-medium text-muted-foreground uppercase">Colour</p>
            <div class="flex flex-wrap gap-2">
              <button
                v-for="entry in THEMES"
                :key="entry.value"
                type="button"
                :aria-label="entry.label"
                :aria-pressed="theme === entry.value"
                class="flex items-center gap-2 rounded-lg border px-2.5 py-1.5 text-xs transition-colors outline-hidden focus-visible:ring-2 focus-visible:ring-ring"
                :class="theme === entry.value ? 'border-primary bg-accent' : 'border-border hover:bg-accent/60'"
                @click="theme = entry.value"
              >
                <span class="flex overflow-hidden rounded-full">
                  <span class="size-4" :style="{ background: entry.ground }" />
                  <span class="size-4" :style="{ background: entry.accent }" />
                </span>
                {{ entry.label }}
              </button>
            </div>
          </div>
          <div class="grid gap-1.5">
            <Label for="qr-message">Line above (optional)</Label>
            <Input
              id="qr-message"
              v-model="message"
              maxlength="48"
              placeholder="Fresh from the coast, every day"
            />
          </div>
        </div>

        <div class="flex flex-wrap items-end gap-4">
          <div class="grid gap-1.5">
            <Label for="qr-size">Size</Label>
            <Select v-model="size">
              <SelectTrigger id="qr-size" class="w-40">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem v-for="entry in SIZES" :key="entry.value" :value="entry.value">
                  {{ entry.label }}
                  <span class="text-muted-foreground">
                    · {{ showcase ? `${geometryFor(entry).perPage} a page` : `${entry.mm}mm` }}
                  </span>
                </SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div class="flex items-center gap-2.5">
            <Checkbox id="show-door" v-model="showDoor" />
            <Label for="show-door" class="font-normal">Include a code for the door</Label>
          </div>
          <div class="flex items-center gap-2.5">
            <Checkbox id="show-cut" v-model="showCutMarks" />
            <Label for="show-cut" class="font-normal">Cut marks</Label>
          </div>
          <p class="text-sm text-muted-foreground">
            {{ cards.length }} {{ cards.length === 1 ? 'code' : 'codes' }} ·
            {{ pages.length }} {{ pages.length === 1 ? 'page' : 'pages' }}
          </p>
          <Button class="ml-auto" :disabled="!cards.length" @click="print">
            <FontAwesomeIcon :icon="['fas', 'print']" />
            Print / Save as PDF
          </Button>
        </div>

        <!-- Which tables ---------------------------------------------------- -->
        <div class="grid gap-2">
          <div class="flex items-center gap-3">
            <p class="text-xs font-medium text-muted-foreground uppercase">Tables</p>
            <Button variant="ghost" size="sm" class="h-6 px-2" @click="selectAll">All</Button>
            <Button
              variant="ghost"
              size="sm"
              class="h-6 px-2"
              @click="chosen = new Set()"
            >
              None
            </Button>
          </div>
          <div class="flex flex-wrap gap-1.5">
            <button
              v-for="table in tables"
              :key="table.id"
              type="button"
              :aria-pressed="chosen.has(table.id)"
              class="rounded-md border px-2 py-1 text-xs transition-colors outline-hidden focus-visible:ring-2 focus-visible:ring-ring"
              :class="chosen.has(table.id)
                ? 'border-primary bg-primary text-primary-foreground'
                : 'border-border bg-muted/50 hover:bg-accent'"
              @click="toggle(table.id)"
            >
              {{ table.label }}
            </button>
          </div>
        </div>

        <p class="text-xs text-muted-foreground">
          Each code points at its table and keeps working when the room is rearranged — the
          diner's session is issued when they scan, not printed on the sticker. The diner page
          is not live yet, so these are for laminating now and scanning once it is.
        </p>
      </div>

      <!-- The sheets -------------------------------------------------------- -->
      <div class="print-sheets grid gap-6 overflow-x-auto print:gap-0 print:overflow-visible">
        <!-- One box per sheet of paper, at its real size and with the real margin, so the
             preview shows where the pages break. A continuous strip hides the one thing
             worth checking before printing forty stickers: whether a card lands half on one
             sheet and half on the next. -->
        <article
          v-for="(page, pageIndex) in pages"
          :key="pageIndex"
          class="print-sheet mx-auto bg-white text-black shadow-lg ring-1 ring-black/10 print:shadow-none print:ring-0"
          :class="pageIndex < pages.length - 1 ? 'break-after-page' : ''"
          :style="{
            width: `${PAGE.width}mm`,
            minHeight: `${PAGE.height}mm`,
            padding: `${PAGE.margin}mm`,
          }"
        >
          <div
            class="grid content-start"
            :style="{
              gridTemplateColumns: `repeat(${perRow}, minmax(0, 1fr))`,
              gap: `${PAGE.gutter}mm`,
            }"
          >
            <div
              v-for="card in page"
              :key="card.key"
              class="relative flex break-inside-avoid flex-col items-center"
            >
              <!-- The cut guide sits outside the card, so a blade following it takes nothing
                   off the artwork. -->
              <span
                v-if="showCutMarks"
                aria-hidden="true"
                class="pointer-events-none absolute -inset-[2mm] border border-dashed border-black/30"
              />
              <!-- Showcase: the standing sign -------------------------- -->
              <div
                v-if="design === 'showcase'"
                class="flex w-full flex-col overflow-hidden rounded-[4mm]"
                :style="{
                  aspectRatio: '3 / 4',
                  background: palette.ground,
                  color: palette.ink,
                }"
              >
                <div class="flex flex-1 flex-col items-center px-[6%] pt-[7%] text-center">
                  <img
                    v-if="restaurant?.logo"
                    :src="restaurant.logo"
                    alt=""
                    class="mb-[3%] max-h-[12%] object-contain"
                  >
                  <p
                    v-else
                    class="mb-[3%] text-[0.9em] font-semibold tracking-[0.22em] uppercase"
                    style="font-size: clamp(0.5rem, 3cqw, 0.85rem)"
                  >
                    {{ active?.name }}
                  </p>

                  <p
                    v-if="message"
                    class="mb-[2%] text-[0.62em] leading-snug tracking-[0.14em] uppercase opacity-70"
                  >
                    {{ message }}
                  </p>

                  <!-- The call to action, and the reason the card works from two metres. -->
                  <p class="text-[2.6em] leading-[0.85] font-black tracking-[-0.02em] uppercase">
                    Scan me
                  </p>
                  <p
                    class="mt-[1.5%] text-[0.78em] leading-tight font-semibold tracking-[0.1em] uppercase"
                    :style="{ color: palette.accent }"
                  >
                    to view our menu
                  </p>

                  <!-- The code on white, with the corner brackets every good sign uses to
                       say "point the camera here". -->
                  <div class="relative mt-[5%] w-[72%] rounded-[3mm] bg-white p-[5%]">
                    <span
                      v-for="corner in ['top-0 left-0 border-t-2 border-l-2 rounded-tl-[2mm]',
                                        'top-0 right-0 border-t-2 border-r-2 rounded-tr-[2mm]',
                                        'bottom-0 left-0 border-b-2 border-l-2 rounded-bl-[2mm]',
                                        'bottom-0 right-0 border-b-2 border-r-2 rounded-br-[2mm]']"
                      :key="corner"
                      class="absolute size-[16%]"
                      :class="corner"
                      :style="{ borderColor: palette.accent }"
                    />
                    <div class="qr aspect-square w-full" v-html="svgByKey[card.key]" />
                  </div>

                  <p
                    class="mt-[4%] rounded-full px-[5%] py-[1.5%] text-[1.05em] leading-none font-bold"
                    :style="{ background: palette.accent, color: palette.ground }"
                  >
                    {{ card.label }}
                  </p>
                </div>

                <!-- The step strip: three things, in the order they happen. -->
                <div
                  class="mt-[5%] grid grid-cols-3 gap-[2%] px-[6%] py-[3.5%] text-center"
                  :style="{ background: 'rgba(0,0,0,0.28)' }"
                >
                  <p
                    v-for="(step, index) in STEPS"
                    :key="step"
                    class="text-[0.5em] leading-tight tracking-[0.08em] uppercase opacity-85"
                  >
                    <span class="block font-black" :style="{ color: palette.accent }">
                      {{ index + 1 }}
                    </span>
                    {{ step }}
                  </p>
                </div>
              </div>

              <!-- Card -------------------------------------------------- -->
              <div
                v-else-if="design === 'card'"
                class="w-full overflow-hidden rounded-[3mm] border border-black/80"
              >
                <p class="bg-black px-2 py-1.5 text-center text-[0.6rem] font-semibold tracking-[0.2em] text-white uppercase">
                  {{ active?.name }}
                </p>
                <div class="flex flex-col items-center gap-1 px-2 py-3">
                  <div
                    class="qr"
                    :style="{ width: `${sizing.mm}mm`, height: `${sizing.mm}mm` }"
                    v-html="svgByKey[card.key]"
                  />
                  <p class="mt-1 text-[1.1rem] leading-none font-bold">{{ card.label }}</p>
                  <p class="text-[0.55rem] tracking-[0.18em] uppercase opacity-60">
                    Scan to order
                  </p>
                </div>
              </div>

              <!-- Table tent -------------------------------------------- -->
              <div
                v-else-if="design === 'tent'"
                class="w-full overflow-hidden rounded-[2mm] border border-black/60"
              >
                <div class="flex rotate-180 flex-col items-center gap-1 px-2 py-3">
                  <div
                    class="qr"
                    :style="{ width: `${sizing.mm}mm`, height: `${sizing.mm}mm` }"
                    v-html="svgByKey[card.key]"
                  />
                  <p class="text-[1rem] leading-none font-bold">{{ card.label }}</p>
                </div>
                <!-- The fold. A dashed rule is the only instruction this needs. -->
                <div class="flex items-center gap-2 px-2">
                  <span class="h-px flex-1 border-t border-dashed border-black/50" />
                  <span class="text-[0.5rem] tracking-[0.2em] uppercase opacity-50">Fold</span>
                  <span class="h-px flex-1 border-t border-dashed border-black/50" />
                </div>
                <div class="flex flex-col items-center gap-1 px-2 py-3">
                  <div
                    class="qr"
                    :style="{ width: `${sizing.mm}mm`, height: `${sizing.mm}mm` }"
                    v-html="svgByKey[card.key]"
                  />
                  <p class="text-[1rem] leading-none font-bold">{{ card.label }}</p>
                </div>
              </div>

              <!-- Badge ------------------------------------------------- -->
              <div
                v-else-if="design === 'badge'"
                class="flex aspect-square w-full flex-col items-center justify-center rounded-full border-2 border-black p-3"
              >
                <p class="text-[0.5rem] tracking-[0.25em] uppercase opacity-70">
                  {{ active?.name }}
                </p>
                <div
                  class="qr my-1.5"
                  :style="{ width: `${sizing.mm * 0.72}mm`, height: `${sizing.mm * 0.72}mm` }"
                  v-html="svgByKey[card.key]"
                />
                <p class="text-[0.95rem] leading-none font-bold">{{ card.label }}</p>
              </div>

              <!-- Plain ------------------------------------------------- -->
              <div v-else class="flex flex-col items-center gap-1">
                <div
                  class="qr"
                  :style="{ width: `${sizing.mm}mm`, height: `${sizing.mm}mm` }"
                  v-html="svgByKey[card.key]"
                />
                <p class="text-[0.85rem] leading-none font-semibold">{{ card.label }}</p>
                <p class="text-[0.55rem] opacity-60">{{ card.caption }}</p>
              </div>
            </div>
          </div>
        </article>
      </div>
    </template>
  </div>
</template>

<!--
  Unscoped for two reasons: the print rules have to reach `body *`, and the QR itself arrives
  as raw markup through `v-html`, which scoped styles never reach.
-->
<style>
.qr svg {
  display: block;
  width: 100%;
  height: 100%;
}

@media print {
  body * {
    visibility: hidden;
  }

  /* The *wrapper* is what gets lifted, not each page: absolutely positioning every sheet at
     the top would stack them all on page one. Inside it the pages flow and break normally. */
  .print-sheets,
  .print-sheets * {
    visibility: visible;
  }

  .print-sheets {
    position: absolute;
    top: 0;
    left: 0;
    width: 100%;
  }

  /* The showcase, card and badge designs carry solid colour; without this a printer drops it
     and the header bar prints as an empty box. */
  .print-sheets,
  .print-sheets * {
    print-color-adjust: exact;
    -webkit-print-color-adjust: exact;
  }
}
</style>
