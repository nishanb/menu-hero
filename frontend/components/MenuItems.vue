<script setup lang="ts">
/**
 * Menu management: the sections down the left, the dishes in them on the right.
 *
 * The rail is the navigation and the table is the work, which is how every POS lays this out
 * and how the people using it already think. "All items" sits at the top because a search
 * across the whole menu is the other thing anyone comes here to do.
 *
 * Categories come from the categories collection *and* from the items themselves. An import
 * creates the sections it names, but an item edited into a section that was later removed
 * would otherwise vanish from every view — so the rail lists what the items actually say,
 * with the ordered categories first.
 *
 * Owners edit; staff read. The greying-out is a courtesy — `assert_can_manage_tenant` on the
 * backend is the boundary that holds.
 */
import type { Category, MenuItem, MenuItemWrite, MenuOptions } from '~/types/api'
import { toApiError } from '~/utils/api-error'

const props = defineProps<{
  tenantId: string
  /** Whether to offer the actions at all. */
  canManage: boolean
}>()

const api = useRestaurantApi()

const items = ref<MenuItem[]>([])
const categories = ref<Category[]>([])
const options = ref<MenuOptions>({
  diets: [],
  order_types: [],
  exposures: [],
  weight_units: [],
  gst_types: [],
})
const loading = ref(true)
const error = ref('')
const busyId = ref('')

const search = ref('')
/**
 * Which section the table is showing.
 *
 * A section is always chosen, the way a POS does it — there is no "everything" row. `null`
 * only means "the menu has not loaded yet"; `''` is the real no-category bucket, which items
 * imported with a blank category land in and which would otherwise be unreachable.
 */
const section = ref<string | null>(null)

/* ------------------------------------------------------------------ the rail */

const countsByCategory = computed(() => {
  const counts = new Map<string, number>()
  for (const item of items.value) {
    counts.set(item.category, (counts.get(item.category) ?? 0) + 1)
  }
  return counts
})

/**
 * Every section this restaurant has, in menu order.
 *
 * Categories the items claim but no category row exists for are listed too — an import
 * creates the sections it names, but a section removed afterwards would otherwise take its
 * dishes out of every view. This is what the item form offers.
 */
const allSections = computed(() => {
  const ordered = categories.value.map(category => category.name)
  const known = new Set(ordered)
  const orphans = [...countsByCategory.value.keys()].filter(name => name && !known.has(name))
  return [...ordered, ...orphans]
})

/** What the rail shows: only sections with something in them. */
const sections = computed(() =>
  allSections.value.filter(name => countsByCategory.value.get(name)),
)

const uncategorised = computed(() => countsByCategory.value.get('') ?? 0)

/* ------------------------------------------------------------------ the table */

/**
 * A search runs across the whole menu, not just the open section.
 *
 * With no "everything" row this is the only way to find a dish whose section you have
 * forgotten — and it is what anyone typing a name expects anyway. The section filter applies
 * only when nothing has been typed.
 */
const visible = computed(() => {
  const needle = search.value.trim().toLowerCase()
  if (needle) {
    return items.value.filter(item =>
      item.name.toLowerCase().includes(needle)
      || item.online_name.toLowerCase().includes(needle)
      || item.short_code.toLowerCase().includes(needle),
    )
  }
  return items.value.filter(item => section.value === null || item.category === section.value)
})

/** The stripe down the left of a row: green for veg, red for non-veg, amber for egg. */
function dietColour(diet: string): string {
  if (diet === 'veg') {
    return 'bg-emerald-600'
  }
  if (diet === 'non-veg') {
    return 'bg-red-600'
  }
  return diet ? 'bg-amber-500' : 'bg-transparent'
}

const money = new Intl.NumberFormat('en-IN', { minimumFractionDigits: 2 })

function price(item: MenuItem): string {
  const value = item.price_from
  return value ? `${item.variations.length ? 'from ' : ''}${money.format(value)}` : '—'
}

/* ------------------------------------------------------------------ editing */

const editing = ref<MenuItem | null>(null)
const formOpen = ref(false)
const saving = ref(false)

function openAdd(): void {
  editing.value = null
  formOpen.value = true
}

function openEdit(item: MenuItem): void {
  editing.value = item
  formOpen.value = true
}

async function save(changes: MenuItemWrite): Promise<void> {
  saving.value = true
  error.value = ''
  try {
    const target = editing.value
    if (target) {
      const updated = await api.updateItem(props.tenantId, target.id, changes)
      items.value = items.value.map(item => (item.id === updated.id ? updated : item))
    }
    else {
      items.value = [...items.value, await api.createItem(props.tenantId, changes)]
    }
    formOpen.value = false
  }
  catch (cause) {
    error.value = toApiError(cause).detail
    formOpen.value = false
  }
  finally {
    saving.value = false
  }
}

/* ------------------------------------------------------------------ removal */

const removing = ref<MenuItem | null>(null)
const removalOpen = ref(false)

function askToRemove(item: MenuItem): void {
  removing.value = item
  removalOpen.value = true
}

async function confirmRemoval(): Promise<void> {
  const target = removing.value
  if (!target) {
    return
  }
  busyId.value = target.id
  error.value = ''
  try {
    await api.deleteItem(props.tenantId, target.id)
    items.value = items.value.filter(item => item.id !== target.id)
  }
  catch (cause) {
    error.value = toApiError(cause).detail
  }
  finally {
    busyId.value = ''
    removing.value = null
  }
}

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const [menu, sectionList, formOptions] = await Promise.all([
      api.menuItems(props.tenantId),
      api.categories(props.tenantId),
      api.menuOptions(props.tenantId),
    ])
    items.value = menu.items
    categories.value = sectionList.categories
    options.value = formOptions
    // With no "everything" row, something has to be selected or the table is empty for no
    // reason. The first section with dishes in it is the one an owner opens the page to see.
    if (section.value === null || !sections.value.includes(section.value)) {
      section.value = sections.value[0] ?? ''
    }
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

    <!-- Nothing on the menu at all --------------------------------------------- -->
    <section
      v-else-if="!items.length"
      class="rounded-xl border border-dashed border-border px-6 py-12 text-center"
    >
      <p class="text-sm text-muted-foreground">
        No items on the menu yet.
      </p>
      <div v-if="canManage" class="mt-4 flex flex-wrap justify-center gap-2">
        <Button size="sm" as-child>
          <NuxtLink to="/menus/import">Import from your POS</NuxtLink>
        </Button>
        <Button size="sm" variant="outline" @click="openAdd">Add one by hand</Button>
      </div>
    </section>

    <template v-else>
      <!-- Toolbar ------------------------------------------------------------- -->
      <div class="flex flex-wrap items-center gap-2">
        <div class="relative min-w-56 flex-1">
          <Label for="menu-search" class="sr-only">Search the menu</Label>
          <Input
            id="menu-search"
            v-model="search"
            placeholder="Search by name or short code"
            class="pl-8"
          />
          <FontAwesomeIcon
            :icon="['fas', 'magnifying-glass']"
            class="pointer-events-none absolute top-1/2 left-2.5 -translate-y-1/2 text-xs text-muted-foreground"
          />
        </div>
        <p class="text-sm whitespace-nowrap text-muted-foreground">
          <template v-if="search.trim()">
            {{ visible.length }} of {{ items.length }} across the menu
          </template>
          <template v-else>{{ visible.length }} in this section</template>
        </p>
        <Button v-if="canManage" size="sm" @click="openAdd">
          <FontAwesomeIcon :icon="['fas', 'plus']" />
          Add item
        </Button>
      </div>

      <div class="grid gap-4 lg:grid-cols-[15rem_1fr] lg:items-start">
        <!-- The sections ---------------------------------------------------- -->
        <!-- `min-w-0`: a grid item's automatic minimum size is its content, so without this
             the longest category name ("Kerala Porota - Non Veg Combos") makes the rail wider
             than the 15rem column it was given, and the counts hang out past its edge. -->
        <!-- Sticky, and scrolling inside itself: a menu with 35 sections is taller than the
             viewport, and a rail that leaves the screen means scrolling back up to change
             section. `lg:items-start` on the grid is what gives it room to stick.
             `dvh` and a 6rem margin because a sticky box *taller* than the viewport is not
             held at `top` at all - it drifts up with the page until its bottom arrives, which
             is exactly the behaviour this is meant to stop. -->
        <aside
          class="grid min-w-0 gap-2 rounded-xl border border-border bg-card p-3 lg:sticky lg:top-4 lg:max-h-[calc(100dvh-6rem)] lg:overflow-y-auto"
        >
          <p class="truncate px-1 text-xs font-medium text-muted-foreground uppercase">
            Categories
          </p>

          <nav class="grid min-w-0 gap-0.5">
            <button
              v-for="name in sections"
              :key="name"
              type="button"
              class="flex min-w-0 items-center justify-between gap-2 rounded-md px-2 py-1.5 text-left text-sm transition-colors outline-hidden focus-visible:ring-2 focus-visible:ring-ring"
              :class="section === name ? 'bg-accent font-medium' : 'hover:bg-accent/60'"
              :title="name"
              @click="section = name"
            >
              <span class="min-w-0 flex-1 truncate">{{ name }}</span>
              <span class="shrink-0 text-xs text-muted-foreground">
                {{ countsByCategory.get(name) ?? 0 }}
              </span>
            </button>
            <button
              v-if="uncategorised"
              type="button"
              class="flex min-w-0 items-center justify-between gap-2 rounded-md px-2 py-1.5 text-left text-sm text-muted-foreground transition-colors outline-hidden focus-visible:ring-2 focus-visible:ring-ring"
              :class="section === '' ? 'bg-accent font-medium' : 'hover:bg-accent/60'"
              @click="section = ''"
            >
              <span class="min-w-0 flex-1 truncate">No category</span>
              <span class="shrink-0 text-xs">{{ uncategorised }}</span>
            </button>
          </nav>
        </aside>

        <!-- The dishes -------------------------------------------------------- -->
        <div class="overflow-x-auto rounded-lg border border-border">
          <!-- `table-fixed`: dish names run to 145 characters in a real export, and an auto
               layout lets the name column take the whole width and push price, image and the
               actions off the right-hand edge. Fixed gives the sized columns what they asked
               for and truncates the name into what is left. -->
          <Table class="table-fixed">
            <TableHeader>
              <TableRow>
                <TableHead class="w-2" />
                <TableHead>Name</TableHead>
                <TableHead>Description</TableHead>
                <TableHead class="w-24 text-right">Price</TableHead>
                <TableHead class="w-14">Image</TableHead>
                <TableHead v-if="canManage" class="w-24 text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              <TableRow
                v-for="item in visible"
                :key="item.id"
                :title="item.is_available ? undefined : 'Off the menu today — see Menu on/off'"
                :class="item.is_available ? '' : 'opacity-55'"
              >
                <!-- The stripe every POS puts here: how a server reads a menu at a glance. -->
                <TableCell class="p-0">
                  <span
                    class="block h-8 w-1 rounded-full"
                    :class="dietColour(item.diet)"
                    :aria-label="item.diet || 'no dietary attribute'"
                  />
                </TableCell>
                <TableCell class="min-w-0">
                  <p class="truncate font-medium" :title="item.name">{{ item.name }}</p>
                  <p
                    v-if="item.online_name && item.online_name !== item.name"
                    class="truncate text-xs text-muted-foreground"
                  >
                    {{ item.online_name }}
                  </p>
                </TableCell>
                <TableCell class="truncate text-sm text-muted-foreground">
                  <span :title="item.description">{{ item.description || '—' }}</span>
                </TableCell>
                <TableCell class="text-right tabular-nums">{{ price(item) }}</TableCell>
                <TableCell>
                  <img
                    v-if="item.image_url"
                    :src="item.image_url"
                    alt=""
                    class="size-8 rounded object-cover"
                  >
                  <FontAwesomeIcon
                    v-else
                    :icon="['fas', 'image']"
                    class="text-muted-foreground/40"
                  />
                </TableCell>
                <TableCell v-if="canManage" class="text-right">
                  <div class="flex items-center justify-end gap-0.5">
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      aria-label="Edit"
                      :disabled="busyId === item.id"
                      @click="openEdit(item)"
                    >
                      <FontAwesomeIcon :icon="['fas', 'pen']" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      aria-label="Remove"
                      class="text-destructive hover:text-destructive"
                      :disabled="busyId === item.id"
                      @click="askToRemove(item)"
                    >
                      <FontAwesomeIcon :icon="['fas', 'trash-can']" />
                    </Button>
                  </div>
                </TableCell>
              </TableRow>
            </TableBody>
          </Table>

          <p v-if="!visible.length" class="px-4 py-10 text-center text-sm text-muted-foreground">
            Nothing here matches.
          </p>
        </div>
      </div>
    </template>

    <!-- Both dialogs render no DOM on the server but a portal anchor in the browser. -->
    <ClientOnly>
      <Dialog v-model:open="formOpen">
        <DialogContent
          class="max-h-[92vh] max-w-[min(96vw,64rem)] overflow-y-auto sm:max-w-[min(96vw,64rem)]"
        >
          <DialogHeader>
            <DialogTitle>{{ editing ? editing.name : 'Add item' }}</DialogTitle>
            <DialogDescription>
              Everything about this dish. Only the name is required.
            </DialogDescription>
          </DialogHeader>
          <MenuItemForm
            :key="editing?.id ?? 'new'"
            :item="editing"
            :tenant-id="tenantId"
            :default-category="section ?? ''"
            :categories="allSections"
            :options="options"
            :busy="saving"
            @submit="save"
            @cancel="formOpen = false"
          />
        </DialogContent>
      </Dialog>

      <AlertDialog v-model:open="removalOpen">
        <AlertDialogContent>
          <AlertDialogTitle>Remove {{ removing?.name }}?</AlertDialogTitle>
          <AlertDialogDescription>
            It goes from the menu. To take it off today's service instead, use Off — that
            keeps the dish and stops it being offered.
          </AlertDialogDescription>
          <AlertDialogFooter>
            <AlertDialogCancel @click="removing = null">Keep it</AlertDialogCancel>
            <AlertDialogAction variant="destructive" @click="confirmRemoval">
              Remove
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </ClientOnly>
  </div>
</template>
