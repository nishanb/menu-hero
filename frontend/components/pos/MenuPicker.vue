<script setup lang="ts">
/**
 * The half of the POS a server taps: the menu, arranged for speed.
 *
 * Sections run down the left as a rail of big buttons, the way every till lays them out: a
 * thumb finds "Drinks" in the same place all night without reading. Search sits over the
 * dishes and matches name and short code, because a server who knows the menu types "ND"
 * rather than scrolling to Neer Dosa. A dish that comes in several forms asks which one
 * before it goes on - a line has one price, and the backend refuses to guess.
 *
 * Dishes that are off the menu are shown dimmed rather than hidden, so a server can tell the
 * table "we're out of that" instead of wondering where it went.
 */
import type { Category, MenuItem, MenuVariation } from '~/types/api'
import { toApiError } from '~/utils/api-error'
import { price } from '~/utils/pos'

const props = defineProps<{ tenantId: string, disabled?: boolean }>()

const emit = defineEmits<{ add: [item: MenuItem, variation: MenuVariation | null] }>()

const api = useRestaurantApi()

const items = ref<MenuItem[]>([])
const categories = ref<Category[]>([])
const loading = ref(true)
const error = ref('')
const search = ref('')
const section = ref<string | null>(null)

const sections = computed(() => {
  const counts = new Map<string, number>()
  for (const item of items.value) {
    counts.set(item.category, (counts.get(item.category) ?? 0) + 1)
  }
  const ordered = categories.value
    .filter(category => category.status === 'active')
    .map(category => category.name)
  const known = new Set(ordered)
  const orphans = [...counts.keys()].filter(name => name && !known.has(name))
  return [...ordered, ...orphans].filter(name => counts.get(name))
})

const visible = computed(() => {
  const needle = search.value.trim().toLowerCase()
  if (needle) {
    return items.value.filter(item =>
      item.name.toLowerCase().includes(needle)
      || item.short_code.toLowerCase().includes(needle),
    )
  }
  return items.value.filter(item => item.category === section.value)
})

/**
 * No "All". Four hundred dishes in one grid is a wall, and the first section is the one a
 * till opens on anyway; the rail is there to slide through the rest.
 */
watch(sections, (list) => {
  if (section.value === null || !list.includes(section.value)) {
    section.value = list[0] ?? null
  }
})

/**
 * The tile wears its diet: a stripe and a wash. Green and red are what every Indian menu
 * already means by them, so a server reads the grid without reading it.
 */
function dietClass(diet: string): string {
  if (diet === 'veg') {
    return 'border-emerald-500/40 bg-emerald-500/10 hover:bg-emerald-500/20'
  }
  if (diet === 'non-veg') {
    return 'border-red-500/40 bg-red-500/10 hover:bg-red-500/20'
  }
  if (diet) {
    return 'border-amber-500/40 bg-amber-500/10 hover:bg-amber-500/20'
  }
  return 'border-border bg-card hover:bg-accent/60'
}

/* ------------------------------------------------------------------ choosing a form */

const choosing = ref<MenuItem | null>(null)
const chooserOpen = ref(false)

function tap(item: MenuItem): void {
  if (!item.is_available || props.disabled) {
    return
  }
  if (item.variations.length) {
    choosing.value = item
    chooserOpen.value = true
    return
  }
  emit('add', item, null)
}

function choose(variation: MenuVariation): void {
  if (choosing.value) {
    emit('add', choosing.value, variation)
  }
  chooserOpen.value = false
}

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const [menu, sectionList] = await Promise.all([
      api.menuItems(props.tenantId),
      api.categories(props.tenantId),
    ])
    items.value = menu.items
    categories.value = sectionList.categories
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
  <div class="grid min-h-0 min-w-0 grid-cols-[11rem_1fr] gap-3">
    <!-- Sections, down the left: a rail of big targets to slide through, the active one
         filled in. Scrolls on its own, so a forty-section menu never squeezes the dishes. -->
    <nav class="flex min-h-0 flex-col gap-1.5 overflow-y-auto pr-0.5" aria-label="Menu sections">
      <button
        v-for="name in sections"
        :key="name"
        type="button"
        class="min-h-14 shrink-0 rounded-lg border px-3 py-3 text-left text-[0.95rem] font-medium transition-colors outline-hidden focus-visible:ring-2 focus-visible:ring-ring"
        :class="section === name && !search ? 'border-primary bg-primary text-primary-foreground' : 'border-border bg-card hover:bg-accent'"
        @click="section = name; search = ''"
      >
        <span class="line-clamp-2 leading-snug">{{ name }}</span>
      </button>
    </nav>

    <div class="flex min-h-0 min-w-0 flex-col gap-3">
      <Alert v-if="error" variant="destructive">
        <AlertDescription>{{ error }}</AlertDescription>
      </Alert>

      <div class="relative shrink-0">
        <Label for="pos-search" class="sr-only">Search the menu</Label>
        <Input id="pos-search" v-model="search" placeholder="Search by name or short code" class="h-10 pl-9" />
        <FontAwesomeIcon
          :icon="['fas', 'magnifying-glass']"
          class="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-xs text-muted-foreground"
        />
      </div>

      <div v-if="loading" class="grid gap-2 sm:grid-cols-3">
        <Skeleton v-for="n in 9" :key="n" class="h-24 w-full rounded-lg" />
      </div>

      <p v-else-if="!items.length" class="rounded-lg border border-dashed border-border px-4 py-10 text-center text-sm text-muted-foreground">
        The menu is empty. <NuxtLink to="/menus/import" class="underline">Import it</NuxtLink> first.
      </p>

      <!-- The dishes. Auto-fill, so a wide terminal gets five across and a tablet three,
           and every tile stays big enough for a thumb. -->
      <div v-else class="grid min-h-0 flex-1 content-start gap-2 overflow-y-auto pr-0.5 [grid-template-columns:repeat(auto-fill,minmax(10.5rem,1fr))]">
        <button
          v-for="item in visible"
          :key="item.id"
          type="button"
          :disabled="!item.is_available || disabled"
          :title="item.is_available ? item.name : `${item.name} — off the menu`"
          class="flex min-h-24 flex-col justify-between rounded-lg border p-3 text-left transition-colors outline-hidden focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-40"
          :class="dietClass(item.diet)"
          @click="tap(item)"
        >
          <span class="line-clamp-2 text-sm leading-snug font-medium">{{ item.name }}</span>
          <span class="mt-1 flex items-baseline justify-between gap-2 text-xs">
            <span class="truncate font-mono text-muted-foreground">{{ item.short_code }}</span>
            <span class="shrink-0 text-sm tabular-nums">
              <template v-if="item.variations.length">from </template>{{ price.format(item.price_from) }}
            </span>
          </span>
        </button>
        <p v-if="!visible.length" class="col-span-full px-3 py-8 text-center text-sm text-muted-foreground">
          Nothing matches.
        </p>
      </div>
    </div>

    <ClientOnly>
      <Dialog v-model:open="chooserOpen">
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{{ choosing?.name }}</DialogTitle>
            <DialogDescription>How should it come?</DialogDescription>
          </DialogHeader>
          <div class="grid gap-2">
            <Button
              v-for="variation in choosing?.variations ?? []"
              :key="variation.name"
              variant="outline"
              class="h-12 justify-between text-base"
              @click="choose(variation)"
            >
              <span>{{ variation.name }}</span>
              <span class="tabular-nums">{{ price.format(variation.price) }}</span>
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </ClientOnly>
  </div>
</template>
