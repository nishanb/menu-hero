<script setup lang="ts">
/**
 * Bringing a menu in from a POS export.
 *
 * Two steps, always, and the first one is the point. Choosing a file only *reads* it — the
 * backend parses, reports how many items it found, which sections are new, and every row it
 * could not make sense of, and writes nothing. Committing is a second, deliberate click.
 * HLD 9.1 puts a person between an import and a live menu; a preview that costs one upload
 * is the cheapest way to keep them there.
 *
 * The commit **replaces** the menu. An export is somebody saying "this is my menu", not a
 * patch to merge, so the confirmation says how many items are about to go.
 */
import type { MenuImportResponse } from '~/types/api'
import { toApiError } from '~/utils/api-error'

const props = defineProps<{
  tenantId: string
  /** Owners import; staff cannot. The backend refuses the write either way. */
  canManage: boolean
}>()

const api = useRestaurantApi()

const file = ref<File | null>(null)
const preview = ref<MenuImportResponse | null>(null)
const done = ref<MenuImportResponse | null>(null)
const reading = ref(false)
const committing = ref(false)
const error = ref('')
const showAllWarnings = ref(false)

/** How many items the menu holds now, so the confirmation can say what is about to go. */
const currentCount = ref<number | null>(null)

const WARNING_PREVIEW = 5

const visibleWarnings = computed(() => {
  const all = preview.value?.warnings ?? []
  return showAllWarnings.value ? all : all.slice(0, WARNING_PREVIEW)
})

async function onFile(event: Event): Promise<void> {
  const chosen = (event.target as HTMLInputElement).files?.[0] ?? null
  file.value = chosen
  preview.value = null
  done.value = null
  error.value = ''
  showAllWarnings.value = false
  if (!chosen) {
    return
  }
  reading.value = true
  try {
    preview.value = await api.importMenu(props.tenantId, chosen, true)
  }
  catch (cause) {
    error.value = toApiError(cause).detail
  }
  finally {
    reading.value = false
  }
}

async function commit(): Promise<void> {
  const chosen = file.value
  if (!chosen) {
    return
  }
  committing.value = true
  error.value = ''
  try {
    done.value = await api.importMenu(props.tenantId, chosen, false)
    preview.value = null
    file.value = null
    currentCount.value = done.value.items_written
  }
  catch (cause) {
    error.value = toApiError(cause).detail
  }
  finally {
    committing.value = false
  }
}

function startOver(): void {
  file.value = null
  preview.value = null
  done.value = null
  error.value = ''
}

/** `1234.5` -> `1,234.50`, and a 0 reads as "—" because a free dish is worth noticing. */
const money = new Intl.NumberFormat('en-IN', { minimumFractionDigits: 2 })

function price(value: number): string {
  return value ? money.format(value) : '—'
}

onMounted(async () => {
  try {
    currentCount.value = (await api.menuItems(props.tenantId)).total
  }
  catch {
    // Only used to word the confirmation; the import works without it.
  }
})
</script>

<template>
  <div class="grid gap-5">
    <Alert v-if="!canManage">
      <FontAwesomeIcon :icon="['fas', 'lock']" />
      <AlertTitle>Read-only</AlertTitle>
      <AlertDescription>
        An owner of this restaurant brings a menu in.
      </AlertDescription>
    </Alert>

    <Alert v-if="error" variant="destructive">
      <FontAwesomeIcon :icon="['fas', 'circle-exclamation']" />
      <AlertTitle>That file could not be used</AlertTitle>
      <AlertDescription>{{ error }}</AlertDescription>
    </Alert>

    <!-- Done ---------------------------------------------------------------- -->
    <section
      v-if="done"
      class="grid gap-3 rounded-xl border border-border bg-card p-5"
    >
      <div>
        <h2 class="text-base font-medium">The menu is in.</h2>
        <p class="mt-1 text-sm text-muted-foreground">
          {{ done.items_written }} items stored<template v-if="done.items_replaced">
            , replacing the {{ done.items_replaced }} that were here</template>.
          <template v-if="done.images">
            {{ done.images }} {{ done.images === 1 ? 'picture' : 'pictures' }} came with them.
          </template>
          <template v-if="done.new_categories.length">
            {{ done.new_categories.length }} new
            {{ done.new_categories.length === 1 ? 'category was' : 'categories were' }} added.
          </template>
        </p>
      </div>
      <div class="flex flex-wrap gap-2">
        <Button size="sm" as-child>
          <NuxtLink to="/menus">See the menu</NuxtLink>
        </Button>
        <Button size="sm" variant="outline" as-child>
          <NuxtLink to="/menus/categories">Order the categories</NuxtLink>
        </Button>
        <Button size="sm" variant="ghost" @click="startOver">Import another file</Button>
      </div>
    </section>

    <!-- Choose --------------------------------------------------------------- -->
    <section v-else-if="canManage" class="grid gap-3 rounded-xl border border-border bg-card p-5">
      <div>
        <h2 class="text-base font-medium">Choose the export</h2>
        <p class="mt-1 text-sm leading-relaxed text-muted-foreground">
          The item export from your POS, as CSV. A picture column is read too, either as a
          link or as base64 in the cell. Choosing a file only reads it — nothing changes
          until you say so.
        </p>
      </div>
      <div class="grid gap-1.5">
        <Label for="menu-file" class="sr-only">Menu export</Label>
        <Input
          id="menu-file"
          type="file"
          accept=".csv,text/csv"
          class="h-auto py-1.5"
          :disabled="reading || committing"
          @change="onFile"
        />
      </div>
      <p v-if="reading" class="text-sm text-muted-foreground">
        <FontAwesomeIcon :icon="['fas', 'spinner']" class="motion-safe:animate-spin" />
        Reading it…
      </p>
    </section>

    <!-- Preview -------------------------------------------------------------- -->
    <template v-if="preview">
      <section class="grid gap-4 rounded-xl border border-border bg-card p-5">
        <div>
          <h2 class="text-base font-medium">
            {{ preview.item_count }} {{ preview.item_count === 1 ? 'item' : 'items' }} found
          </h2>
          <p class="mt-1 text-sm text-muted-foreground">
            Nothing has been written yet.
          </p>
        </div>

        <dl class="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
          <div class="flex items-baseline justify-between gap-4 border-b border-border pb-2">
            <dt class="text-muted-foreground">New categories</dt>
            <dd class="font-medium">{{ preview.new_categories.length }}</dd>
          </div>
          <div class="flex items-baseline justify-between gap-4 border-b border-border pb-2">
            <dt class="text-muted-foreground">Already here</dt>
            <dd class="font-medium">{{ preview.existing_categories.length }}</dd>
          </div>
          <div class="flex items-baseline justify-between gap-4 border-b border-border pb-2">
            <dt class="text-muted-foreground">Pictures</dt>
            <dd class="font-medium">{{ preview.images }}</dd>
          </div>
          <div class="flex items-baseline justify-between gap-4 border-b border-border pb-2">
            <dt class="text-muted-foreground">Rows skipped</dt>
            <dd class="font-medium">{{ preview.skipped }}</dd>
          </div>
          <div class="flex items-baseline justify-between gap-4 border-b border-border pb-2">
            <dt class="text-muted-foreground">Warnings</dt>
            <dd class="font-medium">{{ preview.warnings.length }}</dd>
          </div>
        </dl>

        <div v-if="preview.new_categories.length" class="grid gap-2">
          <p class="text-xs font-medium text-muted-foreground uppercase">Categories to add</p>
          <div class="flex flex-wrap gap-1.5">
            <span
              v-for="name in preview.new_categories"
              :key="name"
              class="rounded-md border border-border bg-muted/50 px-2 py-1 text-xs"
            >{{ name }}</span>
          </div>
        </div>

        <div v-if="preview.warnings.length" class="grid gap-2">
          <p class="text-xs font-medium text-muted-foreground uppercase">Worth a look</p>
          <ul class="grid gap-1 text-sm text-muted-foreground">
            <li v-for="warning in visibleWarnings" :key="warning">— {{ warning }}</li>
          </ul>
          <Button
            v-if="preview.warnings.length > WARNING_PREVIEW"
            variant="ghost"
            size="sm"
            class="justify-self-start"
            @click="showAllWarnings = !showAllWarnings"
          >
            {{ showAllWarnings ? 'Show fewer' : `Show all ${preview.warnings.length}` }}
          </Button>
        </div>
      </section>

      <!-- The first few rows, so the owner can recognise their own menu ------- -->
      <section v-if="preview.sample.length" class="grid gap-2">
        <p class="text-xs font-medium text-muted-foreground uppercase">First few items</p>
        <div class="overflow-x-auto rounded-lg border border-border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Item</TableHead>
                <TableHead>Category</TableHead>
                <TableHead class="w-20">Diet</TableHead>
                <TableHead class="w-28 text-right">Price</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              <TableRow v-for="item in preview.sample" :key="item.name">
                <TableCell class="font-medium">
                  {{ item.name }}
                  <span v-if="item.variations" class="text-xs text-muted-foreground">
                    · {{ item.variations }} variations
                  </span>
                </TableCell>
                <TableCell class="text-muted-foreground">{{ item.category || '—' }}</TableCell>
                <TableCell class="text-muted-foreground">{{ item.diet || '—' }}</TableCell>
                <TableCell class="text-right tabular-nums">{{ price(item.price) }}</TableCell>
              </TableRow>
            </TableBody>
          </Table>
        </div>
      </section>

      <!-- Commit -------------------------------------------------------------- -->
      <section class="flex flex-wrap items-center justify-between gap-3 border-t border-border pt-4">
        <p class="text-sm text-muted-foreground">
          <template v-if="currentCount">
            This replaces the {{ currentCount }}
            {{ currentCount === 1 ? 'item' : 'items' }} on the menu now.
          </template>
          <template v-else>The menu is empty, so nothing is replaced.</template>
        </p>
        <div class="flex gap-2">
          <Button variant="ghost" size="sm" :disabled="committing" @click="startOver">
            Cancel
          </Button>
          <Button size="sm" :disabled="committing" @click="commit">
            <FontAwesomeIcon
              v-if="committing"
              :icon="['fas', 'spinner']"
              class="motion-safe:animate-spin"
            />
            Import {{ preview.item_count }} items
          </Button>
        </div>
      </section>
    </template>
  </div>
</template>
