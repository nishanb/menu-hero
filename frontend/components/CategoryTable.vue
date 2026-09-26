<script setup lang="ts">
/**
 * The sections of one restaurant's menu: name, running order, and whether diners see them.
 *
 * Owners edit; staff read the list, because a server needs to know how the menu is
 * organised. The greying-out is a courtesy — `assert_can_manage_tenant` on the backend is
 * the boundary that actually holds.
 *
 * Rank is a plain number rather than drag-to-reorder. An owner thinks "desserts go last",
 * not "desserts go after cheese", and a number survives two people editing the menu at once
 * in a way a dragged order does not. Ties break on the name, so the list never shuffles.
 */
import type { Category, CategoryStatus, CategoryUpdate } from '~/types/api'
import { toApiError } from '~/utils/api-error'

const props = defineProps<{
  tenantId: string
  /** Whether to offer the actions at all. */
  canManage: boolean
}>()

const api = useRestaurantApi()

const categories = ref<Category[]>([])
const loading = ref(true)
const error = ref('')
/** The row a request is in flight for, so only that row's controls go quiet. */
const busyId = ref('')
/** A move renumbers several rows at once, so it quietens the whole column instead. */
const reordering = ref(false)

const STATUS_LABELS: Record<CategoryStatus, string> = { active: 'Active', hidden: 'Hidden' }

/* ---------------------------------------------------------------- the add / edit dialog */

/** `null` while adding, the category while editing. Also what the dialog title reads from. */
const editing = ref<Category | null>(null)
const formOpen = ref(false)
const form = reactive({ name: '', rank: 0, status: 'active' as CategoryStatus })
const saving = ref(false)
const formError = ref('')

function openAdd(): void {
  editing.value = null
  // One past the last, matching what the backend would choose, so the number in the field is
  // the number that gets stored rather than a placeholder that changes on save.
  const last = categories.value.at(-1)
  Object.assign(form, { name: '', rank: last ? last.rank + 1 : 0, status: 'active' })
  formError.value = ''
  formOpen.value = true
}

function openEdit(category: Category): void {
  editing.value = category
  Object.assign(form, { name: category.name, rank: category.rank, status: category.status })
  formError.value = ''
  formOpen.value = true
}

async function submit(): Promise<void> {
  const name = form.name.trim()
  if (!name) {
    formError.value = 'A category needs a name.'
    return
  }
  saving.value = true
  formError.value = ''
  try {
    const body: CategoryUpdate = { name, rank: form.rank, status: form.status }
    const target = editing.value
    if (target) {
      const updated = await api.updateCategory(props.tenantId, target.id, body)
      categories.value = sorted(categories.value.map(c => (c.id === updated.id ? updated : c)))
    }
    else {
      categories.value = sorted([
        ...categories.value,
        await api.createCategory(props.tenantId, { name, rank: form.rank, status: form.status }),
      ])
    }
    formOpen.value = false
  }
  catch (cause) {
    formError.value = toApiError(cause).detail
  }
  finally {
    saving.value = false
  }
}

/* ------------------------------------------------------------------------ removal */

/**
 * Two refs rather than one, the same as `TeamSettings`. Driving the dialog's `open` off the
 * payload alone looks tidier but silently does nothing: reka-ui closes on the confirm click,
 * that close clears the payload, and the handler then reads `null` and returns.
 */
const removing = ref<Category | null>(null)
const removalOpen = ref(false)

function askToRemove(category: Category): void {
  removing.value = category
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
    await api.deleteCategory(props.tenantId, target.id)
    categories.value = categories.value.filter(c => c.id !== target.id)
  }
  catch (cause) {
    error.value = toApiError(cause).detail
  }
  finally {
    busyId.value = ''
    removing.value = null
  }
}

/* ------------------------------------------------------------------------ the list */

/** Mirrors the backend's order — rank, then name — so a local edit lands where a reload would. */
function sorted(list: Category[]): Category[] {
  return [...list].sort((a, b) => a.rank - b.rank || a.name.localeCompare(b.name))
}

/**
 * Move one section past its neighbour.
 *
 * The whole list is renumbered densely rather than one rank being nudged. Nudging looks
 * cheaper and is quietly broken: ranks may tie, ties fall back to the name, so "move up"
 * would work for Mains above Starters and do visibly nothing for Zuppa above Starters.
 * Renumbering is deterministic whatever the numbers started as, and leaves the ranks in the
 * tidy 0..n order the column implies.
 */
async function move(category: Category, by: -1 | 1): Promise<void> {
  const order = [...categories.value]
  const index = order.findIndex(item => item.id === category.id)
  const target = index + by
  if (index < 0 || target < 0 || target >= order.length) {
    return
  }
  const [moved] = order.splice(index, 1)
  order.splice(target, 0, moved!)

  reordering.value = true
  error.value = ''
  try {
    const next: Category[] = []
    for (const [rank, item] of order.entries()) {
      next.push(
        item.rank === rank ? item : await api.updateCategory(props.tenantId, item.id, { rank }),
      )
    }
    categories.value = next
  }
  catch (cause) {
    error.value = toApiError(cause).detail
    // Several rows may have moved before the failure, so the local copy is no longer a
    // guess worth keeping.
    await load()
  }
  finally {
    reordering.value = false
  }
}

async function toggleStatus(category: Category): Promise<void> {
  busyId.value = category.id
  error.value = ''
  try {
    const status: CategoryStatus = category.status === 'active' ? 'hidden' : 'active'
    const updated = await api.updateCategory(props.tenantId, category.id, { status })
    categories.value = categories.value.map(c => (c.id === updated.id ? updated : c))
  }
  catch (cause) {
    error.value = toApiError(cause).detail
  }
  finally {
    busyId.value = ''
  }
}

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    categories.value = (await api.categories(props.tenantId)).categories
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

    <div v-if="canManage" class="flex justify-end">
      <Button size="sm" @click="openAdd">
        <FontAwesomeIcon :icon="['fas', 'plus']" />
        Add category
      </Button>
    </div>

    <div v-if="loading" class="grid gap-2">
      <Skeleton class="h-12 w-full" />
      <Skeleton class="h-12 w-full" />
    </div>

    <section
      v-else-if="!categories.length"
      class="rounded-xl border border-dashed border-border px-6 py-12 text-center"
    >
      <p class="text-sm text-muted-foreground">
        No categories yet. Starters, Mains, Desserts — the headings a diner reads before
        they read a single dish.
      </p>
      <Button v-if="canManage" class="mt-4" size="sm" @click="openAdd">
        Add the first one
      </Button>
    </section>

    <div v-else class="overflow-x-auto rounded-lg border border-border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Name</TableHead>
            <TableHead class="w-24">Rank</TableHead>
            <TableHead class="w-28">Status</TableHead>
            <TableHead v-if="canManage" class="w-44 text-right">Actions</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          <TableRow v-for="(category, index) in categories" :key="category.id">
            <TableCell class="font-medium">{{ category.name }}</TableCell>
            <TableCell class="tabular-nums text-muted-foreground">{{ category.rank }}</TableCell>
            <TableCell>
              <Badge :variant="category.status === 'active' ? 'secondary' : 'outline'">
                {{ STATUS_LABELS[category.status] }}
              </Badge>
            </TableCell>
            <TableCell v-if="canManage" class="text-right">
              <div class="flex items-center justify-end gap-0.5">
                <Button
                  variant="ghost"
                  size="icon-sm"
                  aria-label="Move up"
                  :disabled="index === 0 || reordering"
                  @click="move(category, -1)"
                >
                  <FontAwesomeIcon :icon="['fas', 'chevron-up']" />
                </Button>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  aria-label="Move down"
                  :disabled="index === categories.length - 1 || reordering"
                  @click="move(category, 1)"
                >
                  <FontAwesomeIcon :icon="['fas', 'chevron-down']" />
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  :disabled="busyId === category.id"
                  @click="toggleStatus(category)"
                >
                  {{ category.status === 'active' ? 'Hide' : 'Show' }}
                </Button>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  aria-label="Edit"
                  :disabled="busyId === category.id"
                  @click="openEdit(category)"
                >
                  <FontAwesomeIcon :icon="['fas', 'pen']" />
                </Button>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  aria-label="Remove"
                  class="text-destructive hover:text-destructive"
                  :disabled="busyId === category.id"
                  @click="askToRemove(category)"
                >
                  <FontAwesomeIcon :icon="['fas', 'trash-can']" />
                </Button>
              </div>
            </TableCell>
          </TableRow>
        </TableBody>
      </Table>
    </div>

    <!-- Both dialogs render no DOM on the server but a portal anchor in the browser, so
         they go inside ClientOnly to keep hydration quiet. -->
    <ClientOnly>
      <Dialog v-model:open="formOpen">
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{{ editing ? 'Edit category' : 'Add category' }}</DialogTitle>
            <DialogDescription>
              A heading on the menu. Rank decides the running order — lower is read first.
            </DialogDescription>
          </DialogHeader>

          <form class="grid gap-4" @submit.prevent="submit">
            <Alert v-if="formError" variant="destructive">
              <AlertDescription>{{ formError }}</AlertDescription>
            </Alert>

            <div class="grid gap-1.5">
              <Label for="category-name">Name</Label>
              <Input
                id="category-name"
                v-model="form.name"
                maxlength="60"
                placeholder="Starters"
                required
              />
            </div>

            <div class="grid gap-4 sm:grid-cols-2">
              <div class="grid gap-1.5">
                <Label for="category-rank">Rank</Label>
                <Input
                  id="category-rank"
                  v-model.number="form.rank"
                  type="number"
                  min="0"
                  max="999"
                />
              </div>
              <div class="grid gap-1.5">
                <Label for="category-status">Status</Label>
                <Select v-model="form.status">
                  <SelectTrigger id="category-status">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="active">Active</SelectItem>
                    <SelectItem value="hidden">Hidden</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>

            <DialogFooter>
              <Button type="button" variant="ghost" @click="formOpen = false">Cancel</Button>
              <Button type="submit" :disabled="saving">
                <FontAwesomeIcon
                  v-if="saving"
                  :icon="['fas', 'spinner']"
                  class="motion-safe:animate-spin"
                />
                {{ editing ? 'Save changes' : 'Add category' }}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <AlertDialog v-model:open="removalOpen">
        <AlertDialogContent>
          <AlertDialogTitle>Remove {{ removing?.name }}?</AlertDialogTitle>
          <AlertDialogDescription>
            The heading goes from the menu. Hiding it instead keeps it here and takes it off
            what diners read.
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
