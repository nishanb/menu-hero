<script setup lang="ts">
/**
 * The menu as a designed sheet of paper, in four templates, printed by the browser.
 *
 * **Why the browser and not a PDF library.** What comes out of `window.print()` with a
 * "Save as PDF" destination is a real PDF with vector text, the actual fonts, and page breaks
 * the engine worked out from the content. The alternatives are worse in ways that show on
 * paper: `jsPDF` + `html2canvas` rasterises, so a menu printed at 300 dpi looks like a
 * screenshot; a server-side renderer (WeasyPrint, headless Chromium) means system libraries
 * or a browser in the container for output no better than this one. The cost is one extra
 * click in the print dialog, and it is worth it.
 *
 * Only dishes that are on the menu are printed. A paper menu listing something the kitchen
 * has run out of is the specific failure this whole feature is supposed to avoid.
 */
// Imported here rather than in `nuxt.config`, so the display face is code-split with this
// component and no other page pays for a font only the printed menu uses.
import '@fontsource/playfair-display/400.css'
import '@fontsource/playfair-display/500.css'
import '@fontsource/playfair-display/600.css'
import '@fontsource/playfair-display/400-italic.css'
import type { Category, MenuItem } from '~/types/api'
import { toApiError } from '~/utils/api-error'

const props = defineProps<{ tenantId: string }>()

const api = useRestaurantApi()
const { active } = useRestaurants()

const items = ref<MenuItem[]>([])
const categories = ref<Category[]>([])
const loading = ref(true)
const error = ref('')

/**
 * Four templates, and they are not four skins of one thing.
 *
 * Two are *designed* — a menu that goes on a table is a piece of the room, and a plain list
 * of names and prices is a missed opportunity. Two are utilities, and look like it on
 * purpose: the till and the kitchen wall want density and nothing else.
 */
const TEMPLATES = [
  {
    value: 'elegant',
    label: 'Elegant',
    blurb: 'Cream, serif, letter-spaced. The one that reads like a restaurant.',
    designed: true,
  },
  {
    value: 'signature',
    label: 'Signature',
    blurb: 'Dark masthead, ruled sections, a legend. Bold and modern.',
    designed: true,
  },
  {
    value: 'compact',
    label: 'Compact',
    blurb: 'Three dense columns. For a long menu that has to fit on few pages.',
    designed: false,
  },
  {
    value: 'counter',
    label: 'Counter sheet',
    blurb: 'A plain table. For the till, the kitchen wall, or a takeaway counter.',
    designed: false,
  },
] as const

type Template = (typeof TEMPLATES)[number]['value']

const template = ref<Template>('elegant')
const paper = ref<'A4' | 'Letter'>('A4')
const showDescriptions = ref(true)
const showDiet = ref(true)
const showCover = ref(true)

/**
 * `@page` cannot read a CSS variable, so the paper size is written into a style tag instead.
 * 14mm all round is a margin every domestic printer can actually reach; the designed
 * templates print edge to edge instead and lay out their own margins, which is what lets the
 * masthead bleed.
 */
const bleeds = computed(() => template.value === 'signature')

useHead({
  style: [
    {
      innerHTML: computed(
        () => `@page { size: ${paper.value}; margin: ${bleeds.value ? '0' : '14mm'}; }`,
      ),
    },
  ],
})

/* ------------------------------------------------------------------ the restaurant */

const restaurant = computed(() => active.value?.detail)

const services = computed(() =>
  (restaurant.value?.services ?? []).map(name => name.charAt(0).toUpperCase() + name.slice(1)),
)

/**
 * The licence numbers, read as labels.
 *
 * On the sheet because in India an FSSAI number is expected on a printed menu, and this is
 * the page a diner would look for it on. Whatever an owner keeps in the restaurant's
 * "Additional information" is what prints.
 */
const extras = computed(() =>
  Object.entries(restaurant.value?.extras ?? {}).map(([key, value]) => ({
    label: key
      .replace(/_/g, ' ')
      .replace(/^\w+/, word =>
        word.length <= 5 ? word.toUpperCase() : word.charAt(0).toUpperCase() + word.slice(1),
      ),
    value,
  })),
)

/* ------------------------------------------------------------------ the menu itself */

const groups = computed(() => {
  const byCategory = new Map<string, MenuItem[]>()
  for (const item of items.value) {
    if (!item.is_available) {
      continue
    }
    const list = byCategory.get(item.category) ?? []
    list.push(item)
    byCategory.set(item.category, list)
  }
  const ordered = categories.value
    .filter(category => category.status === 'active')
    .map(category => category.name)
  const known = new Set(ordered)
  const orphans = [...byCategory.keys()].filter(name => name && !known.has(name))
  const names = [...ordered, ...orphans, ...(byCategory.has('') ? [''] : [])]
  return names
    .filter(name => byCategory.get(name)?.length)
    .map(name => ({ name, items: byCategory.get(name) ?? [] }))
})

const printed = computed(() => groups.value.reduce((total, g) => total + g.items.length, 0))

/** Which marks actually appear, so the legend explains the menu in hand and not a general one. */
const diets = computed(() => {
  const found = new Set<string>()
  for (const group of groups.value) {
    for (const item of group.items) {
      if (item.diet) {
        found.add(item.diet)
      }
    }
  }
  return DIET_MARKS.filter(entry => found.has(entry.diet))
})

const DIET_MARKS = [
  { diet: 'veg', mark: 'V', label: 'Vegetarian' },
  { diet: 'egg', mark: 'E', label: 'Contains egg' },
  { diet: 'non-veg', mark: 'N', label: 'Non-vegetarian' },
]

const money = new Intl.NumberFormat('en-IN', { minimumFractionDigits: 0 })

function price(item: MenuItem): string {
  return item.price_from ? money.format(item.price_from) : ''
}

function dietMark(diet: string): string {
  return DIET_MARKS.find(entry => entry.diet === diet)?.mark ?? ''
}

/** `Boiled Rice 249 · White Rice 259` — the choice is part of the dish, so it prints. */
function variations(item: MenuItem): string {
  return item.variations
    .map(variation => `${variation.name} ${money.format(variation.price)}`)
    .join('   ·   ')
}

/** The printable height of one page, so a cover fills it on screen as it will on paper. */
const pageHeight = computed(() => {
  const full = paper.value === 'A4' ? 297 : 279
  return `${bleeds.value ? full : full - 28}mm`
})

/**
 * Hand the sheet to the browser's own print pipeline.
 *
 * A method rather than `window.print()` inline in the template: `window` is not on the
 * component instance, so the template cannot see it.
 */
function print(): void {
  window.print()
}

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const [menu, sections] = await Promise.all([
      api.menuItems(props.tenantId),
      api.categories(props.tenantId),
    ])
    items.value = menu.items
    categories.value = sections.categories
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
      <Skeleton class="h-96 w-full" />
    </div>

    <section
      v-else-if="!printed"
      class="rounded-xl border border-dashed border-border px-6 py-12 text-center"
    >
      <p class="text-sm text-muted-foreground">
        <template v-if="items.length">
          Everything is off the menu, so there is nothing to print.
        </template>
        <template v-else>There is no menu to print yet.</template>
      </p>
      <Button class="mt-4" size="sm" as-child>
        <NuxtLink :to="items.length ? '/menus/availability' : '/menus/import'">
          {{ items.length ? 'Turn some dishes back on' : 'Import your menu' }}
        </NuxtLink>
      </Button>
    </section>

    <template v-else>
      <!-- Controls -------------------------------------------------------- -->
      <div class="grid gap-4 rounded-xl border border-border bg-card p-4 print:hidden">
        <div class="grid gap-2">
          <p class="text-xs font-medium text-muted-foreground uppercase">Template</p>
          <div class="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
            <button
              v-for="option in TEMPLATES"
              :key="option.value"
              type="button"
              :aria-pressed="template === option.value"
              class="rounded-lg border px-3 py-2.5 text-left transition-colors outline-hidden focus-visible:ring-2 focus-visible:ring-ring"
              :class="template === option.value
                ? 'border-primary bg-accent'
                : 'border-border hover:bg-accent/60'"
              @click="template = option.value"
            >
              <span class="flex items-center gap-1.5 text-sm font-medium">
                {{ option.label }}
                <Badge v-if="option.designed" variant="secondary" class="px-1.5 py-0 text-[0.6rem]">
                  Designed
                </Badge>
              </span>
              <span class="mt-0.5 block text-xs leading-snug text-muted-foreground">
                {{ option.blurb }}
              </span>
            </button>
          </div>
        </div>

        <div class="flex flex-wrap items-end gap-4">
          <div class="grid gap-1.5">
            <Label for="paper">Paper</Label>
            <Select v-model="paper">
              <SelectTrigger id="paper" class="w-32">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="A4">A4</SelectItem>
                <SelectItem value="Letter">Letter</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div class="flex items-center gap-2.5">
            <Checkbox id="show-cover" v-model="showCover" />
            <Label for="show-cover" class="font-normal">Cover page</Label>
          </div>
          <div class="flex items-center gap-2.5">
            <Checkbox id="show-descriptions" v-model="showDescriptions" />
            <Label for="show-descriptions" class="font-normal">Descriptions</Label>
          </div>
          <div class="flex items-center gap-2.5">
            <Checkbox id="show-diet" v-model="showDiet" />
            <Label for="show-diet" class="font-normal">Veg marks</Label>
          </div>
          <p class="text-sm text-muted-foreground">
            {{ printed }} dishes · {{ groups.length }} sections
          </p>
          <Button class="ml-auto" @click="print">
            <FontAwesomeIcon :icon="['fas', 'print']" />
            Print / Save as PDF
          </Button>
        </div>

        <p class="text-xs text-muted-foreground">
          Only dishes that are on the menu are printed. Choose “Save as PDF” as the
          destination, and turn on “Background graphics” so the designed templates keep their
          colour.
        </p>
      </div>

      <!-- The sheet -------------------------------------------------------- -->
      <div class="overflow-x-auto print:overflow-visible">
        <article
          class="print-sheet mx-auto"
          :class="[
            paper === 'A4' ? 'w-[210mm]' : 'w-[216mm]',
            template === 'elegant' ? 'menu-elegant bg-[#faf7ef] text-[#221d16]' : 'bg-white text-black',
            template === 'signature' ? 'menu-signature' : '',
          ]"
        >
          <!-- ============================================ Elegant ========== -->
          <template v-if="template === 'elegant'">
            <section
              v-if="showCover"
              class="flex flex-col items-center justify-center gap-6 px-[18mm] py-[18mm] text-center break-after-page"
              :style="{ minHeight: pageHeight }"
            >
              <img
                v-if="restaurant?.logo"
                :src="restaurant.logo"
                alt=""
                class="max-h-[40mm] max-w-[70mm] object-contain"
              >
              <div class="w-full">
                <p class="text-[0.62rem] tracking-[0.5em] uppercase opacity-60">Est. menu</p>
                <h1 class="menu-display mt-3 text-[3.1rem] leading-[1.05] tracking-[0.06em]">
                  {{ active?.name }}
                </h1>
              </div>
              <div class="flex w-full items-center gap-4 opacity-40">
                <span class="h-px flex-1 bg-current" />
                <span class="size-1.5 rotate-45 bg-current" />
                <span class="h-px flex-1 bg-current" />
              </div>
              <p v-if="restaurant?.description" class="menu-display max-w-sm text-[0.95rem] leading-relaxed italic">
                {{ restaurant.description }}
              </p>
              <p v-if="services.length" class="text-[0.6rem] tracking-[0.35em] uppercase opacity-70">
                {{ services.join('  ·  ') }}
              </p>
              <div class="mt-auto w-full text-[0.58rem] leading-relaxed opacity-60">
                <p v-if="restaurant?.location_url" class="break-all">{{ restaurant.location_url }}</p>
                <p v-if="extras.length" class="mt-1">
                  <span v-for="(extra, index) in extras" :key="extra.label">
                    <template v-if="index">  ·  </template>{{ extra.label }} {{ extra.value }}
                  </span>
                </p>
              </div>
            </section>

            <div class="px-[18mm] py-[16mm]">
              <header v-if="!showCover" class="mb-8 text-center">
                <h1 class="menu-display text-[2.3rem] tracking-[0.18em] uppercase">
                  {{ active?.name }}
                </h1>
                <p v-if="restaurant?.description" class="mx-auto mt-2 max-w-md text-[0.7rem] leading-relaxed opacity-70">
                  {{ restaurant.description }}
                </p>
                <div class="mt-4 flex items-center gap-4 opacity-40">
                  <span class="h-px flex-1 border-t border-dashed border-current" />
                  <span class="size-1.5 rotate-45 bg-current" />
                  <span class="h-px flex-1 border-t border-dashed border-current" />
                </div>
              </header>

              <div class="columns-2 gap-[12mm]">
                <section
                  v-for="group in groups"
                  :key="group.name || 'none'"
                  class="mb-7 break-inside-avoid-column"
                >
                  <h2 class="menu-display mb-3 text-[1.05rem] tracking-[0.16em] uppercase">
                    {{ group.name || 'Also' }}
                  </h2>
                  <div
                    v-for="item in group.items"
                    :key="item.id"
                    class="mb-2.5 break-inside-avoid"
                  >
                    <div class="flex items-baseline gap-2">
                      <p class="min-w-0 flex-1 text-[0.82rem] leading-snug">
                        {{ item.name }}
                        <span v-if="showDiet && dietMark(item.diet)" class="ml-0.5 align-super text-[0.55rem] opacity-60">
                          {{ dietMark(item.diet) }}
                        </span>
                      </p>
                      <p class="shrink-0 text-[0.82rem] tabular-nums">{{ price(item) }}</p>
                    </div>
                    <p
                      v-if="showDescriptions && item.description"
                      class="mt-0.5 text-[0.62rem] leading-snug opacity-55"
                    >{{ item.description }}</p>
                    <p
                      v-if="item.variations.length"
                      class="mt-0.5 text-[0.62rem] leading-snug opacity-70"
                    >{{ variations(item) }}</p>
                  </div>
                </section>
              </div>

              <footer class="mt-8 break-inside-avoid border-t border-dashed border-current/30 pt-4 text-[0.58rem] leading-relaxed opacity-70">
                <p v-if="diets.length && showDiet">
                  <span v-for="(entry, index) in diets" :key="entry.diet">
                    <template v-if="index">   ·   </template>{{ entry.mark }} — {{ entry.label }}
                  </span>
                </p>
                <p v-if="extras.length" class="mt-1">
                  <span v-for="(extra, index) in extras" :key="extra.label">
                    <template v-if="index">   ·   </template>{{ extra.label }} {{ extra.value }}
                  </span>
                </p>
              </footer>
            </div>
          </template>

          <!-- ============================================ Signature ======== -->
          <template v-else-if="template === 'signature'">
            <!-- The masthead bleeds, which is why this template prints with no page margin
                 and lays out its own instead. -->
            <!-- As a cover the masthead is the whole page and the type is centred; inline
                 it is a band at the top with the name sitting on the rule. Anchoring the
                 title low works on a band and leaves a void on a page. -->
            <header
              class="flex flex-col bg-[#14110f] px-[16mm] text-[#faf7ef]"
              :class="[
                showCover
                  ? 'break-after-page justify-center py-[20mm]'
                  : 'justify-end pt-[26mm] pb-[10mm]',
              ]"
              :style="showCover ? { minHeight: pageHeight } : {}"
            >
              <img
                v-if="restaurant?.logo"
                :src="restaurant.logo"
                alt=""
                class="max-h-[26mm] max-w-[52mm] object-contain"
                :class="showCover ? 'mb-8' : 'mb-auto'"
              >
              <p
                v-if="showCover"
                class="mb-4 text-[0.58rem] tracking-[0.5em] uppercase opacity-50"
              >
                Menu
              </p>
              <h1 class="text-[3.4rem] leading-[0.95] font-semibold tracking-[-0.02em] uppercase">
                {{ active?.name }}
              </h1>
              <p v-if="restaurant?.description" class="mt-3 max-w-md text-[0.75rem] leading-relaxed opacity-75">
                {{ restaurant.description }}
              </p>
              <p v-if="services.length" class="mt-4 text-[0.58rem] tracking-[0.35em] uppercase opacity-60">
                {{ services.join('  ·  ') }}
              </p>
              <div
                v-if="showCover && (restaurant?.location_url || extras.length)"
                class="mt-auto pt-10 text-[0.55rem] leading-relaxed opacity-45"
              >
                <p v-if="restaurant?.location_url" class="break-all">
                  {{ restaurant.location_url }}
                </p>
                <p v-if="extras.length" class="mt-1">
                  <span v-for="(extra, index) in extras" :key="extra.label">
                    <template v-if="index">   ·   </template>{{ extra.label }} {{ extra.value }}
                  </span>
                </p>
              </div>
            </header>

            <div class="px-[16mm] py-[12mm]">
              <div class="columns-2 gap-[10mm]">
                <section
                  v-for="group in groups"
                  :key="group.name || 'none'"
                  class="mb-6 break-inside-avoid-column"
                >
                  <h2 class="mb-2 flex items-center gap-2 text-[0.78rem] font-bold tracking-[0.1em] uppercase">
                    <span class="shrink-0">{{ group.name || 'Also' }}</span>
                    <span class="h-px flex-1 bg-black/25" />
                  </h2>
                  <div
                    v-for="item in group.items"
                    :key="item.id"
                    class="mb-2 break-inside-avoid"
                  >
                    <div class="flex items-baseline gap-2">
                      <p class="min-w-0 flex-1 text-[0.8rem] leading-snug font-semibold">
                        {{ item.name }}
                        <span v-if="showDiet && dietMark(item.diet)" class="ml-0.5 align-super text-[0.55rem] font-normal opacity-60">
                          {{ dietMark(item.diet) }}
                        </span>
                      </p>
                      <p class="shrink-0 text-[0.8rem] font-semibold tabular-nums">{{ price(item) }}</p>
                    </div>
                    <p
                      v-if="showDescriptions && item.description"
                      class="text-[0.63rem] leading-snug italic opacity-65"
                    >{{ item.description }}</p>
                    <p
                      v-if="item.variations.length"
                      class="text-[0.63rem] leading-snug opacity-80"
                    >{{ variations(item) }}</p>
                  </div>
                </section>
              </div>

              <!-- The legend, as a boxed aside. Only marks that appear are explained. -->
              <section
                v-if="showDiet && diets.length"
                class="mt-6 break-inside-avoid border border-black/25 p-3"
              >
                <div class="flex flex-wrap gap-x-8 gap-y-1 text-[0.66rem]">
                  <span v-for="entry in diets" :key="entry.diet" class="flex items-baseline gap-1.5">
                    <span class="font-bold">{{ entry.mark }}</span>
                    <span class="opacity-70">{{ entry.label }}</span>
                  </span>
                </div>
                <p class="mt-2 text-[0.6rem] leading-snug opacity-60">
                  Please tell a member of the team about any allergy or dietary requirement.
                </p>
              </section>
            </div>

            <footer
              v-if="extras.length || restaurant?.location_url"
              class="bg-[#14110f] px-[16mm] py-[7mm] text-[0.58rem] leading-relaxed text-[#faf7ef]/80"
            >
              <p v-if="restaurant?.location_url" class="break-all">{{ restaurant.location_url }}</p>
              <p v-if="extras.length" class="mt-1">
                <span v-for="(extra, index) in extras" :key="extra.label">
                  <template v-if="index">   ·   </template>{{ extra.label }} {{ extra.value }}
                </span>
              </p>
            </footer>
          </template>

          <!-- ============================================ Compact =========== -->
          <template v-else-if="template === 'compact'">
            <header class="border-b-2 border-black px-[14mm] pt-[14mm] pb-4 text-center">
              <h1 class="text-2xl font-semibold tracking-tight">{{ active?.name }}</h1>
            </header>
            <div class="columns-3 gap-6 px-[14mm] py-6 text-[0.72rem] leading-snug">
              <section
                v-for="group in groups"
                :key="group.name || 'none'"
                class="mb-3 break-inside-avoid-column"
              >
                <h2 class="mb-1 border-b border-black pb-0.5 text-[0.7rem] font-bold tracking-wide uppercase">
                  {{ group.name || 'Also' }}
                </h2>
                <p
                  v-for="item in group.items"
                  :key="item.id"
                  class="flex items-baseline justify-between gap-2"
                >
                  <span class="min-w-0">
                    {{ item.name }}
                    <span v-if="showDiet && dietMark(item.diet)" class="align-super text-[0.7em]">
                      {{ dietMark(item.diet) }}
                    </span>
                  </span>
                  <span class="shrink-0 tabular-nums">{{ price(item) }}</span>
                </p>
              </section>
            </div>
          </template>

          <!-- ============================================ Counter =========== -->
          <template v-else>
            <header class="border-b-2 border-black px-[14mm] pt-[14mm] pb-4">
              <h1 class="text-2xl font-semibold tracking-tight">{{ active?.name }}</h1>
            </header>
            <div class="px-[14mm] py-6">
              <table class="w-full border-collapse text-[0.8rem]">
                <template v-for="group in groups" :key="group.name || 'none'">
                  <thead>
                    <tr>
                      <th
                        colspan="3"
                        class="border-b border-black pt-3 pb-1 text-left text-[0.8rem] font-bold tracking-wide uppercase"
                      >
                        {{ group.name || 'Also' }}
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr
                      v-for="item in group.items"
                      :key="item.id"
                      class="break-inside-avoid border-b border-black/15"
                    >
                      <td class="w-6 py-1 align-top">
                        <span v-if="showDiet">{{ dietMark(item.diet) }}</span>
                      </td>
                      <td class="py-1 align-top">
                        {{ item.name }}
                        <span
                          v-if="showDescriptions && item.description"
                          class="block text-[0.8em] leading-snug text-black/60"
                        >{{ item.description }}</span>
                      </td>
                      <td class="w-16 py-1 text-right align-top tabular-nums">
                        {{ price(item) }}
                      </td>
                    </tr>
                  </tbody>
                </template>
              </table>
            </div>
          </template>
        </article>
      </div>
    </template>
  </div>
</template>

<!--
  Deliberately NOT scoped: the whole point is to reach `body *`, and a scoped rule cannot.
  The recipe is the well-worn one - hide everything, then make the sheet and its subtree
  visible again and lift it to the top of the page. `display: none` on the siblings would be
  simpler and is wrong here: the sheet lives inside the sidebar layout, so hiding its
  ancestors would hide it too.
-->
<style>
.menu-display {
  font-family: 'Playfair Display', ui-serif, Georgia, serif;
}

.menu-elegant {
  font-family: ui-serif, Georgia, 'Times New Roman', serif;
}

@media print {
  body * {
    visibility: hidden;
  }

  .print-sheet,
  .print-sheet * {
    visibility: visible;
  }

  .print-sheet {
    position: absolute;
    top: 0;
    left: 0;
    width: 100%;
  }

  /* Printers drop background graphics by default, which would take the cream ground and the
     dark masthead with them. This asks for them back; the print dialog can still refuse, and
     the copy under the controls says so. */
  .print-sheet,
  .print-sheet * {
    print-color-adjust: exact;
    -webkit-print-color-adjust: exact;
  }
}
</style>
