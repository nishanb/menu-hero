<script setup lang="ts">
/**
 * The floor plan as **Settings** shows it: the saved room, read-only, with a way in.
 *
 * A view by default, editing behind a deliberate act. Arranging a floor is a task, not a
 * setting — it wants width and an explicit Save — so the drag-and-drop lives in a dialog
 * and this page keeps showing what the restaurant actually looks like right now. Anyone
 * looking up which table is A3 gets an answer without a chance of moving it.
 *
 * The working copy belongs to `useFloorPlan` and is owned here rather than by the dialog:
 * closing the dialog therefore keeps unsaved work instead of throwing it away, and this
 * panel keeps rendering the *saved* plan the whole time, so the page never claims a change
 * that has not been made.
 */
const props = defineProps<{
  tenantId: string
  /** Owners edit; staff read. The backend refuses the write either way. */
  canManage: boolean
}>()

const tenantId = computed(() => props.tenantId)
const plan = useFloorPlan(tenantId)

const editing = ref(false)

const tables = computed(() => plan.saved.value?.tables ?? [])

/**
 * Whether there is a room to look at yet.
 *
 * Gates the header's Edit button: with nothing drawn there is no floor plan to edit, and
 * the empty state below already carries the one thing worth doing. Two buttons that mean
 * the same thing, one of them mislabelled, is worse than one.
 */
const hasPlan = computed(() => plan.savedElements.value.length > 0)
</script>

<template>
  <div class="grid gap-5">
    <Alert v-if="plan.error.value && !editing" variant="destructive">
      <FontAwesomeIcon :icon="['fas', 'circle-exclamation']" />
      <AlertTitle>The floor plan could not be loaded</AlertTitle>
      <AlertDescription>{{ plan.error.value }}</AlertDescription>
    </Alert>

    <Skeleton v-if="plan.loading.value" class="h-80 w-full rounded-xl" />

    <template v-else>
      <!-- Only what the screen cannot say for itself. A saved confirmation, a table count
           and a "nothing here yet" are all restatements of the canvas below; unsaved work
           sitting in a closed dialog is the one thing that is genuinely invisible. -->
      <div
        v-if="canManage && (hasPlan || plan.dirty.value)"
        class="flex flex-wrap items-center justify-end gap-3"
      >
        <p v-if="plan.dirty.value" class="mr-auto text-sm text-muted-foreground">
          Unsaved changes are waiting in the editor.
        </p>
        <Button v-if="hasPlan" variant="outline" size="sm" @click="editing = true">
          <FontAwesomeIcon :icon="['fas', 'pen']" />
          {{ plan.dirty.value ? 'Continue editing' : 'Edit floor plan' }}
        </Button>
      </div>

      <!-- The saved room, and nothing that can move it ------------------------ -->
      <!-- Capped: a 800-unit room would otherwise push the tables list off the page. -->
      <FloorPlanCanvas
        v-if="hasPlan"
        frame-class="max-h-[60vh]"
        :elements="plan.savedElements.value"
        :width="plan.width.value"
        :height="plan.height.value"
        :selected-id="null"
        preview
      />

      <section
        v-else
        class="rounded-xl border border-dashed border-border px-6 py-12 text-center"
      >
        <p class="text-sm text-muted-foreground">
          Draw the room and the tables on it — they are what QR codes get printed for.
        </p>
        <Button v-if="canManage" class="mt-4" size="sm" @click="editing = true">
          {{ plan.dirty.value ? 'Continue editing' : 'Create the floor plan' }}
        </Button>
        <p v-else class="mt-2 text-sm text-muted-foreground">
          An owner of this restaurant sets it up.
        </p>
      </section>

      <!-- The tables themselves, which is what the rest of the app will use ---- -->
      <div v-if="tables.length" class="grid gap-2">
        <p class="text-xs font-medium text-muted-foreground uppercase">Tables</p>
        <div class="flex flex-wrap gap-1.5">
          <span
            v-for="table in tables"
            :key="table.id"
            class="rounded-md border border-border bg-muted/50 px-2 py-1 text-xs"
          >
            {{ table.label }}
            <span class="text-muted-foreground">
              · {{ table.seats }} {{ table.seats === 1 ? 'seat' : 'seats' }}
            </span>
          </span>
        </div>
      </div>
    </template>

    <!-- Editing, deliberately elsewhere -------------------------------------- -->
    <Dialog v-model:open="editing">
      <!-- `open-auto-focus` prevented: the first focusable thing is a shape button, and
           opening the editor with "Round" already ringed reads as a click about to happen.
           Focus stays on the dialog, which is what carries the description. -->
      <DialogContent
        class="max-h-[92vh] max-w-[min(96vw,84rem)] overflow-y-auto sm:max-w-[min(96vw,84rem)]"
        @open-auto-focus.prevent
      >
        <DialogHeader>
          <DialogTitle>Arrange the floor</DialogTitle>
          <DialogDescription>
            Drag tables into place and pull a corner to resize. Nothing changes for the
            restaurant until you save.
          </DialogDescription>
        </DialogHeader>
        <FloorPlanEditor :plan="plan" @saved="editing = false" @close="editing = false" />
      </DialogContent>
    </Dialog>
  </div>
</template>
