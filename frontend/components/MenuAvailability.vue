<script setup lang="ts">
/**
 * Menu on/off: what is being served right now.
 *
 * Every section on one page, each with its dishes and a switch, because taking things off is
 * something a floor manager does in a burst at the start of service — three dishes here, a
 * whole section there — and paging between categories to do it would be the wrong shape. The
 * rail jumps to a section rather than filtering to it.
 *
 * Nothing here publishes anything. Availability is a *service* decision: it changes what a
 * diner is offered tonight and never writes a new version of the menu, which is why it lives
 * apart from the menu editor and why the wording never says "save".
 */
import type { Category, MenuItem } from '~/types/api'
import { toApiError } from '~/utils/api-error'

const props = defineProps<{
  tenantId: string
  /** Owners switch dishes; staff see what is on. */
  canManage: boolean
}>()

const api = useRestaurantApi()

const items = ref<MenuItem[]>([])
const categories = ref<Category[]>([])
const loading = ref(true)
const error = ref('')
/** Ids with a request in flight, so only those rows go quiet. */
const busy = ref<Set<string>>(new Set())
const selected = ref<Set<string>>(new Set())

/* ------------------------------------------------------------------ grouping */

const groups = computed(() => {
  const byCategory = new Map<string, MenuItem[]>()
  for (const item of items.value) {
    const list = byCategory.get(item.category) ?? []
    list.push(item)
    byCategory.set(item.category, list)
  }
  // Menu order first, then anything the items claim that has no category row, then the
  // no-category bucket last — it is a loose end, not a section.
  const ordered = categories.value.map(category => category.name)
  const known = new Set(ordered)
  const orphans = [...byCategory.keys()].filter(name => name && !known.has(name))
  const names = [...ordered, ...orphans, ...(byCategory.has('') ? [''] : [])]
  return names
    .filter(name => byCategory.get(name)?.length)
    .map(name => ({ name, items: byCategory.get(name) ?? [] }))
})

const offCount = computed(() => items.value.filter(item => !item.is_available).length)

function onCount(group: { items: MenuItem[] }): number {
  return group.items.filter(item => item.is_available).length
}

/** An id safe to put in `id`/`href`: section names contain spaces, slashes and dashes. */
function anchor(name: string): string {
  return `section-${name.replace(/[^A-Za-z0-9]+/g, '-').toLowerCase() || 'none'}`
}

function jumpTo(name: string): void {
  document.getElementById(anchor(name))?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

/* ------------------------------------------------------------------ switching */

function markBusy(ids: string[], working: boolean): void {
  const next = new Set(busy.value)
  for (const id of ids) {
    if (working) {
      next.add(id)
    }
    else {
      next.delete(id)
    }
  }
  busy.value = next
}

/**
 * Applied locally the moment the server agrees, rather than re-fetching 407 items to learn
 * about one switch. `changed` is not read: it counts what the server altered, and a dish
 * already in the state asked for is a success with a count of zero.
 */
function applyLocally(ids: Set<string>, on: boolean): void {
  items.value = items.value.map(item =>
    ids.has(item.id) ? { ...item, is_available: on } : item,
  )
}

async function switchItems(ids: string[], on: boolean): Promise<void> {
  if (!ids.length) {
    return
  }
  markBusy(ids, true)
  error.value = ''
  try {
    await api.setAvailability(props.tenantId, { item_ids: ids, on })
    applyLocally(new Set(ids), on)
  }
  catch (cause) {
    error.value = toApiError(cause).detail
  }
  finally {
    markBusy(ids, false)
  }
}

async function switchSection(name: string, on: boolean): Promise<void> {
  const group = groups.value.find(each => each.name === name)
  if (!group) {
    return
  }
  const ids = group.items.map(item => item.id)
  markBusy(ids, true)
  error.value = ''
  try {
    // By section, not by id: one call whatever the section holds, and it stays right even if
    // somebody adds a dish to it while this page is open.
    await api.setAvailability(props.tenantId, { category: name, on })
    applyLocally(new Set(ids), on)
  }
  catch (cause) {
    error.value = toApiError(cause).detail
  }
  finally {
    markBusy(ids, false)
  }
}

/* ------------------------------------------------------------------ selection */

function toggleSelected(id: string): void {
  const next = new Set(selected.value)
  if (next.has(id)) {
    next.delete(id)
  }
  else {
    next.add(id)
  }
  selected.value = next
}

function toggleSection(name: string, checked: boolean): void {
  const group = groups.value.find(each => each.name === name)
  const next = new Set(selected.value)
  for (const item of group?.items ?? []) {
    if (checked) {
      next.add(item.id)
    }
    else {
      next.delete(item.id)
    }
  }
  selected.value = next
}

function sectionChecked(group: { items: MenuItem[] }): boolean {
  return group.items.length > 0 && group.items.every(item => selected.value.has(item.id))
}

async function switchSelected(on: boolean): Promise<void> {
  await switchItems([...selected.value], on)
  selected.value = new Set()
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
  <div class="grid gap-4">
    <Alert v-if="error" variant="destructive">
      <FontAwesomeIcon :icon="['fas', 'circle-exclamation']" />
      <AlertTitle>That did not go through</AlertTitle>
      <AlertDescription>{{ error }}</AlertDescription>
    </Alert>

    <div v-if="loading" class="grid gap-2">
      <Skeleton class="h-10 w-full" />
      <Skeleton class="h-64 w-full" />
    </div>

    <section
      v-else-if="!items.length"
      class="rounded-xl border border-dashed border-border px-6 py-12 text-center"
    >
      <p class="text-sm text-muted-foreground">
        There is nothing on the menu to switch on or off yet.
      </p>
      <Button v-if="canManage" class="mt-4" size="sm" as-child>
        <NuxtLink to="/menus/import">Import your menu</NuxtLink>
      </Button>
    </section>

    <template v-else>
      <div class="flex flex-wrap items-center gap-3">
        <p class="text-sm text-muted-foreground">
          <template v-if="offCount">
            {{ offCount }} of {{ items.length }} off the menu right now
          </template>
          <template v-else>Everything is on.</template>
        </p>
        <!-- The bulk bar only exists while something is picked; a permanently disabled row of
             buttons is furniture. -->
        <div v-if="canManage && selected.size" class="ml-auto flex items-center gap-2">
          <p class="text-sm font-medium">{{ selected.size }} selected</p>
          <Button variant="outline" size="sm" @click="switchSelected(true)">Turn on</Button>
          <Button variant="outline" size="sm" @click="switchSelected(false)">Turn off</Button>
          <Button variant="ghost" size="sm" @click="selected = new Set()">Clear</Button>
        </div>
      </div>

      <div class="grid gap-4 lg:grid-cols-[15rem_1fr] lg:items-start">
        <!-- The rail jumps rather than filters: this page is meant to be read straight down. -->
        <aside
          class="grid min-w-0 gap-2 rounded-xl border border-border bg-card p-3 lg:sticky lg:top-4 lg:max-h-[calc(100dvh-6rem)] lg:overflow-y-auto"
        >
          <p class="truncate px-1 text-xs font-medium text-muted-foreground uppercase">
            Sections
          </p>
          <nav class="grid min-w-0 gap-0.5">
            <button
              v-for="group in groups"
              :key="group.name || 'none'"
              type="button"
              class="flex min-w-0 items-center justify-between gap-2 rounded-md px-2 py-1.5 text-left text-sm transition-colors outline-hidden hover:bg-accent/60 focus-visible:ring-2 focus-visible:ring-ring"
              :title="group.name || 'No category'"
              @click="jumpTo(group.name)"
            >
              <span class="min-w-0 flex-1 truncate">{{ group.name || 'No category' }}</span>
              <span class="shrink-0 text-xs text-muted-foreground">
                {{ onCount(group) }}/{{ group.items.length }}
              </span>
            </button>
          </nav>
        </aside>

        <!-- Every section, one after another ---------------------------------- -->
        <div class="grid gap-6">
          <section v-for="group in groups" :key="group.name || 'none'" :id="anchor(group.name)">
            <div class="mb-2 flex flex-wrap items-center gap-3">
              <div class="flex min-w-0 items-center gap-2.5">
                <Checkbox
                  v-if="canManage"
                  :id="`pick-${anchor(group.name)}`"
                  :model-value="sectionChecked(group)"
                  :aria-label="`Select every dish in ${group.name || 'No category'}`"
                  @update:model-value="toggleSection(group.name, Boolean($event))"
                />
                <h2 class="truncate text-sm font-medium">
                  {{ group.name || 'No category' }}
                </h2>
                <span class="shrink-0 text-xs text-muted-foreground">
                  {{ onCount(group) }} of {{ group.items.length }} on
                </span>
              </div>
              <div v-if="canManage" class="ml-auto flex gap-2">
                <Button variant="ghost" size="sm" @click="switchSection(group.name, true)">
                  All on
                </Button>
                <Button variant="ghost" size="sm" @click="switchSection(group.name, false)">
                  All off
                </Button>
              </div>
            </div>

            <div class="overflow-hidden rounded-lg border border-border">
              <div
                v-for="item in group.items"
                :key="item.id"
                class="flex items-center gap-3 border-b border-border px-3 py-2 last:border-b-0"
                :class="item.is_available ? '' : 'bg-muted/30'"
              >
                <Checkbox
                  v-if="canManage"
                  :model-value="selected.has(item.id)"
                  :aria-label="`Select ${item.name}`"
                  @update:model-value="toggleSelected(item.id)"
                />
                <!-- The dot is the thing a manager scans for; the switch is what they touch. -->
                <span
                  class="size-2.5 shrink-0 rounded-full"
                  :class="item.is_available ? 'bg-emerald-600' : 'bg-muted-foreground/40'"
                  :aria-label="item.is_available ? 'On' : 'Off'"
                />
                <p
                  class="min-w-0 flex-1 truncate text-sm"
                  :class="item.is_available ? '' : 'text-muted-foreground'"
                  :title="item.name"
                >
                  {{ item.name }}
                </p>
                <span class="shrink-0 text-xs tabular-nums text-muted-foreground">
                  {{ item.price_from ? item.price_from.toFixed(2) : '—' }}
                </span>
                <Switch
                  v-if="canManage"
                  :model-value="item.is_available"
                  :disabled="busy.has(item.id)"
                  :aria-label="`${item.name} on the menu`"
                  @update:model-value="switchItems([item.id], Boolean($event))"
                />
                <span v-else class="shrink-0 text-xs text-muted-foreground">
                  {{ item.is_available ? 'On' : 'Off' }}
                </span>
              </div>
            </div>
          </section>
        </div>
      </div>
    </template>
  </div>
</template>
