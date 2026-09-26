<script setup lang="ts">
/**
 * The page behind the QR code on the table: `/restaurant/<id>/order?table=<table>`.
 *
 * No session, no desktop. A phone at a table wants three things - what is there, how much,
 * and a way to say "this one" - so the page is the menu with a sticky search and section
 * strip, an Add on every dish, and a bar at the thumb that opens the round. Ordering goes
 * straight to the kitchen as a ticket on the restaurant's own board, the same shape a
 * captain's ticket has.
 *
 * Without a `table` the menu still shows (it is the door's code too), but ordering is not
 * offered: there is nowhere to send it.
 */
import type { PublicItem, PublicOrderOut, PublicVariation } from '~/types/api'
import { toApiError } from '~/utils/api-error'
import { money } from '~/utils/pos'

definePageMeta({ layout: 'diner' })

const route = useRoute()
const api = useDinerApi()

const restaurantId = computed(() => String(route.params.id ?? ''))
const tableId = computed(() => {
  const raw = route.query.table
  return typeof raw === 'string' && raw ? raw : null
})

const { data: menu, error: loadError, pending } = await useAsyncData(
  () => `diner-menu:${restaurantId.value}:${tableId.value ?? ''}`,
  () => api.menu(restaurantId.value, tableId.value),
)

useHead({ title: () => menu.value?.restaurant.name ?? 'Menu' })

const cart = useDinerCart(restaurantId.value, tableId.value)

/* ------------------------------------------------------------------ finding a dish */

const search = ref('')

/**
 * Filter state lives here; the sheet edits it. Diet chips stack (veg *and* egg is a real
 * diet), the price cap is one switch, sort is one of three. All of it applies inside each
 * section, so the menu keeps its shape while it narrows.
 */
const PRICE_CAP = 200

const diets = ref<Set<string>>(new Set())
const underCap = ref(false)
const sort = ref<'' | 'asc' | 'desc'>('')
const filtersOpen = ref(false)
const sectionsOpen = ref(false)
const chatOpen = ref(false)

/**
 * The welcome shows once per visit. Session storage rather than local: a diner back the
 * next week should be welcomed again; one who locked the phone should not.
 */
const welcomed = ref(true)
onMounted(() => {
  try {
    welcomed.value = sessionStorage.getItem(`mh-welcomed:${restaurantId.value}`) === '1'
  }
  catch {
    welcomed.value = true
  }
})

function welcomeDone(chat: boolean): void {
  welcomed.value = true
  try {
    sessionStorage.setItem(`mh-welcomed:${restaurantId.value}`, '1')
  }
  catch {
    // Private mode: the welcome shows again next time. No harm.
  }
  if (chat) {
    chatOpen.value = true
  }
}

const activeFilters = computed(() => [
  ...[...diets.value].map(value => ({
    key: `diet:${value}`,
    label: { 'veg': 'Veg', 'non-veg': 'Non-veg', 'egg': 'Egg' }[value] ?? value,
    clear: () => {
      const next = new Set(diets.value)
      next.delete(value)
      diets.value = next
    },
  })),
  ...(underCap.value ? [{ key: 'cap', label: `Under ₹${PRICE_CAP}`, clear: () => { underCap.value = false } }] : []),
  ...(sort.value
    ? [{ key: 'sort', label: sort.value === 'asc' ? 'Price ↑' : 'Price ↓', clear: () => { sort.value = '' } }]
    : []),
])

const filtering = computed(() => activeFilters.value.length > 0)

const sections = computed(() => {
  const needle = search.value.trim().toLowerCase()
  return (menu.value?.sections ?? [])
    .map((section) => {
      let items = section.items
      if (needle) {
        items = items.filter(item =>
          item.name.toLowerCase().includes(needle) || item.description.toLowerCase().includes(needle),
        )
      }
      if (diets.value.size) {
        items = items.filter(item => diets.value.has(item.diet))
      }
      if (underCap.value) {
        items = items.filter(item => item.price_from <= PRICE_CAP)
      }
      if (sort.value) {
        const sign = sort.value === 'asc' ? 1 : -1
        items = [...items].sort((a, b) => sign * (a.price_from - b.price_from))
      }
      return { name: section.name, items }
    })
    .filter(section => section.items.length)
})

const matches = computed(() => sections.value.reduce((n, section) => n + section.items.length, 0))

const contents = computed(() => sections.value.map(section => ({ name: section.name, count: section.items.length })))

function anchor(name: string): string {
  return `s-${name.toLowerCase().replace(/[^a-z0-9]+/g, '-')}`
}

function jump(name: string): void {
  document.getElementById(anchor(name))?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

/* ------------------------------------------------------------------ choosing */

const choosing = ref<PublicItem | null>(null)
const chooserOpen = ref(false)

function add(item: PublicItem): void {
  if (item.variations.length) {
    choosing.value = item
    chooserOpen.value = true
    return
  }
  cart.add(item, null)
}

function choose(item: PublicItem, variation: PublicVariation): void {
  cart.add(item, variation)
  chooserOpen.value = false
}

function less(item: PublicItem): void {
  const line = cart.lines.value.find(entry => entry.item_id === item.id && !entry.variation)
  if (line) {
    cart.setQuantity(line.key, line.quantity - 1)
  }
}

/* ------------------------------------------------------------------ the round */

const cartOpen = ref(false)
const sending = ref(false)
const sendError = ref('')
const placed = ref<PublicOrderOut | null>(null)

async function place(): Promise<void> {
  if (!tableId.value) {
    return
  }
  sending.value = true
  sendError.value = ''
  try {
    placed.value = await api.order(restaurantId.value, {
      table_id: tableId.value,
      lines: cart.lines.value.map(line => ({
        item_id: line.item_id,
        variation: line.variation,
        quantity: line.quantity,
        note: line.note,
      })),
    })
    cart.clear()
  }
  catch (cause) {
    sendError.value = toApiError(cause).detail
  }
  finally {
    sending.value = false
  }
}

function done(): void {
  placed.value = null
  cartOpen.value = false
}
</script>

<template>
  <div class="flex min-h-dvh flex-col">
    <!-- Cannot load: say so, plainly ------------------------------------------- -->
    <div v-if="loadError" class="grid flex-1 place-items-center p-6 text-center">
      <div>
        <p class="text-lg font-semibold">This menu is not available</p>
        <p class="mt-1 text-sm text-muted-foreground">
          The code may be out of date. Ask a server for a menu.
        </p>
      </div>
    </div>

    <div v-else-if="pending || !menu" class="grid gap-3 p-4">
      <Skeleton class="h-16 w-full rounded-xl" />
      <Skeleton class="h-10 w-full rounded-lg" />
      <Skeleton v-for="n in 5" :key="n" class="h-24 w-full rounded-xl" />
    </div>

    <template v-else>
      <!-- Who and where ---------------------------------------------------------- -->
      <header class="flex items-center gap-3 px-4 pt-[max(1rem,env(safe-area-inset-top))] pb-3">
        <img
          v-if="menu.restaurant.logo"
          :src="menu.restaurant.logo"
          alt=""
          class="size-12 shrink-0 rounded-xl object-cover"
        >
        <div class="min-w-0 flex-1">
          <h1 class="truncate text-lg leading-tight font-semibold">{{ menu.restaurant.name }}</h1>
          <p v-if="menu.restaurant.description" class="line-clamp-1 text-xs text-muted-foreground">
            {{ menu.restaurant.description }}
          </p>
        </div>
        <Badge v-if="menu.table" variant="secondary" class="shrink-0 text-sm">
          Table {{ menu.table.label }}
        </Badge>
      </header>

      <!-- Sticky: the search, and one button for everything else. A phone screen is for
           the menu; the controls stay out of the way until they are wanted. -->
      <div class="sticky top-0 z-10 bg-background/95 backdrop-blur-sm">
        <div class="flex items-center gap-2 px-4 pb-2">
          <div class="relative min-w-0 flex-1">
            <Label for="diner-search" class="sr-only">Search the menu</Label>
            <Input id="diner-search" v-model="search" placeholder="Search the menu" class="h-11 rounded-xl pl-10 text-base" />
            <FontAwesomeIcon
              :icon="['fas', 'magnifying-glass']"
              class="pointer-events-none absolute top-1/2 left-3.5 -translate-y-1/2 text-sm text-muted-foreground"
            />
          </div>
          <Button
            variant="outline"
            class="relative h-11 w-11 shrink-0 rounded-xl"
            :class="filtering ? 'border-primary' : ''"
            aria-label="Filters"
            @click="filtersOpen = true"
          >
            <FontAwesomeIcon :icon="['fas', 'sliders']" />
            <span
              v-if="filtering"
              class="absolute -top-1.5 -right-1.5 grid size-5 place-items-center rounded-full bg-primary text-[11px] font-semibold text-primary-foreground tabular-nums"
            >
              {{ activeFilters.length }}
            </span>
          </Button>
        </div>
        <!-- Only what has been chosen, each with its own way off. -->
        <div v-if="filtering" class="flex gap-1.5 overflow-x-auto px-4 pb-2 [scrollbar-width:none]">
          <button
            v-for="filter in activeFilters"
            :key="filter.key"
            type="button"
            class="flex shrink-0 items-center gap-1.5 rounded-full bg-primary py-1 pr-2 pl-3 text-xs font-medium text-primary-foreground whitespace-nowrap"
            :aria-label="`Remove ${filter.label}`"
            @click="filter.clear()"
          >
            {{ filter.label }}
            <FontAwesomeIcon :icon="['fas', 'xmark']" class="text-[10px] opacity-80" />
          </button>
        </div>
        <Separator />
      </div>

      <!-- The menu ---------------------------------------------------------------- -->
      <main class="flex-1 px-4 pb-28">
        <p v-if="!sections.length" class="py-16 text-center text-sm text-muted-foreground">
          <template v-if="search">Nothing matches “{{ search }}”.</template>
          <template v-else-if="filtering">Nothing matches those filters.</template>
          <template v-else>The menu is empty right now.</template>
        </p>
        <section
          v-for="section in sections"
          :id="anchor(section.name)"
          :key="section.name"
          class="scroll-mt-20 pt-4"
        >
          <h2 class="text-base font-semibold">{{ section.name }}</h2>
          <div class="divide-y divide-border">
            <DinerItemRow
              v-for="item in section.items"
              :key="item.id"
              :item="item"
              :quantity="cart.quantityOf(item)"
              @add="add"
              @less="less"
            />
          </div>
        </section>
      </main>

      <!-- Floating, where the thumb is: chat on the left, the table of contents on the
           right; both climb above the round's bar when there is one. (The `_` around the
           `+` is Tailwind's spelling of the spaces `calc()` insists on.) -->
      <div
        v-if="!search"
        class="pointer-events-none fixed inset-x-0 z-20 mx-auto flex w-full max-w-md justify-between px-4 transition-[bottom]"
        :class="cart.count.value ? 'bottom-[calc(4.5rem_+_max(1rem,env(safe-area-inset-bottom)))]' : 'bottom-[max(1rem,env(safe-area-inset-bottom))]'"
      >
        <Button variant="secondary" class="pointer-events-auto h-10 rounded-full border border-border px-4 font-semibold shadow-lg" @click="chatOpen = true">
          <FontAwesomeIcon :icon="['fas', 'robot']" />
          Chat &amp; order
        </Button>
        <Button v-if="contents.length > 1" class="pointer-events-auto h-10 rounded-full px-4 font-semibold shadow-lg" @click="sectionsOpen = true">
          <FontAwesomeIcon :icon="['fas', 'utensils']" />
          Menu
        </Button>
      </div>

      <!-- The round, at the thumb ----------------------------------------------------- -->
      <div
        v-if="cart.count.value"
        class="fixed inset-x-0 bottom-0 z-20 mx-auto w-full max-w-md px-4 pb-[max(1rem,env(safe-area-inset-bottom))]"
      >
        <Button class="h-13 w-full justify-between rounded-xl px-5 text-base shadow-lg" @click="cartOpen = true">
          <span>{{ cart.count.value }} {{ cart.count.value === 1 ? 'item' : 'items' }} · ₹{{ money.format(cart.total.value) }}</span>
          <span class="flex items-center gap-2 font-semibold">
            View order
            <FontAwesomeIcon :icon="['fas', 'chevron-up']" class="text-xs" />
          </span>
        </Button>
      </div>

      <ClientOnly>
        <DinerWelcome
          v-if="!welcomed"
          :name="menu.restaurant.name"
          :logo="menu.restaurant.logo"
          :ready="true"
          @chat="welcomeDone(true)"
          @browse="welcomeDone(false)"
        />
        <DinerChatSheet
          v-model:open="chatOpen"
          :sections="menu.sections"
          :restaurant="menu.restaurant.name"
          @add="add"
        />
        <DinerFilterSheet
          v-model:open="filtersOpen"
          v-model:diets="diets"
          v-model:under-cap="underCap"
          v-model:sort="sort"
          :price-cap="PRICE_CAP"
          :matches="matches"
        />
        <DinerSectionsSheet v-model:open="sectionsOpen" :sections="contents" @jump="jump" />
        <DinerVariationSheet v-model:open="chooserOpen" :item="choosing" @choose="choose" />
        <DinerCartSheet
          v-model:open="cartOpen"
          :lines="cart.lines.value"
          :total="cart.total.value"
          :table="menu.table?.label ?? null"
          :sending="sending"
          :error="sendError"
          :placed="placed"
          @quantity="cart.setQuantity"
          @note="cart.setNote"
          @place="place"
          @done="done"
        />
      </ClientOnly>
    </template>
  </div>
</template>
