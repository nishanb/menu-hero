<script setup lang="ts">
/**
 * The editing half of the floor plan, shown in a dialog rather than on the settings page.
 *
 * Arranging a room is a task with a beginning and an end, not a setting to be nudged: it
 * wants width, a scratch buffer and an explicit Save. The page behind keeps showing the
 * saved plan the whole time, so there is never a moment where the restaurant appears to
 * have changed because someone dragged a table and thought better of it.
 *
 * The buffer belongs to `useFloorPlan`, which the settings panel owns and passes in — so
 * closing the dialog does not throw work away, and reopening resumes exactly where it left
 * off. Only Save and Discard decide anything.
 *
 * The interaction itself lives in `FloorPlanCanvas`; this component is the panel around it.
 */
import { useEventListener } from '@vueuse/core'
import type { FloorPlanStore } from '~/composables/useFloorPlan'
import type { ElementShape } from '~/types/api'

const props = defineProps<{ plan: FloorPlanStore }>()

const emit = defineEmits<{ saved: [], close: [] }>()

const plan = props.plan

/** The four table shapes, drawn as themselves rather than labelled with an icon. */
const SHAPES: Array<{ shape: ElementShape, label: string, css: string }> = [
  { shape: 'circle', label: 'Round', css: 'rounded-full size-5' },
  { shape: 'square', label: 'Square', css: 'rounded-[3px] size-5' },
  { shape: 'diamond', label: 'Diamond', css: 'rounded-[2px] size-4 rotate-45' },
  { shape: 'rectangle', label: 'Long', css: 'rounded-[3px] h-4 w-7' },
]

async function onSave(): Promise<void> {
  if (await plan.save()) {
    emit('saved')
  }
}

/**
 * Delete removes the selection, Escape drops it.
 *
 * Guarded on the focused element: the seat count and the table name are text fields, and
 * backspacing inside one must not delete the table being renamed. Escape stops at the
 * selection rather than closing the dialog, which is why it is handled here at all.
 */
useEventListener('keydown', (event: KeyboardEvent) => {
  const id = plan.selectedId.value
  if (!id) {
    return
  }
  const target = event.target as HTMLElement | null
  if (target && (target.isContentEditable || ['INPUT', 'TEXTAREA'].includes(target.tagName))) {
    return
  }
  if (event.key === 'Escape') {
    event.stopPropagation()
    plan.selectedId.value = null
  }
  if (event.key === 'Delete' || event.key === 'Backspace') {
    event.preventDefault()
    plan.remove(id)
  }
})
</script>

<template>
  <div class="grid gap-4">
    <Alert v-if="plan.error.value" variant="destructive">
      <FontAwesomeIcon :icon="['fas', 'circle-exclamation']" />
      <AlertTitle>That did not go through</AlertTitle>
      <AlertDescription>{{ plan.error.value }}</AlertDescription>
    </Alert>

    <div class="grid gap-4 lg:grid-cols-[15rem_1fr] lg:items-start">
      <!-- Panel -------------------------------------------------------------- -->
      <aside class="grid gap-5 rounded-xl border border-border bg-card p-4">
        <div class="grid gap-2">
          <p class="text-xs font-medium text-muted-foreground uppercase">Add a table</p>
          <div class="grid grid-cols-2 gap-2">
            <button
              v-for="option in SHAPES"
              :key="option.shape"
              type="button"
              class="flex items-center gap-2 rounded-lg border border-border px-2.5 py-2 text-sm transition-colors outline-hidden hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring"
              @click="plan.add('table', option.shape)"
            >
              <span
                class="shrink-0 border-2 border-dashed border-muted-foreground/60"
                :class="option.css"
              />
              {{ option.label }}
            </button>
          </div>
        </div>

        <div class="grid gap-2">
          <p class="text-xs font-medium text-muted-foreground uppercase">Add to the room</p>
          <div class="grid grid-cols-2 gap-2">
            <Button variant="outline" size="sm" @click="plan.add('wall')">
              <span class="h-1.5 w-4 rounded-xs bg-muted-foreground/50" />
              Wall
            </Button>
            <Button variant="outline" size="sm" @click="plan.add('text')">
              <FontAwesomeIcon :icon="['fas', 'font']" />
              Text
            </Button>
          </div>
        </div>

        <!-- Tables, as the list this whole screen exists to produce ------------ -->
        <div class="grid gap-2">
          <p class="text-xs font-medium text-muted-foreground uppercase">Tables</p>
          <div v-if="plan.tables.value.length" class="flex flex-wrap gap-1.5">
            <button
              v-for="table in plan.tables.value"
              :key="table.id"
              type="button"
              class="rounded-md border px-2 py-1 text-xs transition-colors outline-hidden focus-visible:ring-2 focus-visible:ring-ring"
              :class="table.id === plan.selectedId.value
                ? 'border-primary bg-primary text-primary-foreground'
                : 'border-border bg-muted/50 hover:bg-accent'"
              @click="plan.selectedId.value = table.id"
            >
              {{ table.label || 'Unnamed' }}
              <span class="opacity-70">· {{ table.seats }}</span>
            </button>
          </div>
          <p v-else class="text-sm text-muted-foreground">
            None yet. Tables you add here are what QR codes get printed for.
          </p>
        </div>

        <!-- Whatever is selected ---------------------------------------------- -->
        <template v-if="plan.selected.value">
          <Separator />
          <div class="grid gap-3">
            <div class="flex items-center justify-between gap-2">
              <p class="text-xs font-medium text-muted-foreground uppercase">Selected</p>
              <Button
                variant="ghost"
                size="sm"
                class="h-7 px-2 text-destructive hover:text-destructive"
                @click="plan.remove(plan.selected.value!.id)"
              >
                <FontAwesomeIcon :icon="['fas', 'trash-can']" />
                Remove
              </Button>
            </div>

            <template v-if="plan.selected.value.kind === 'table'">
              <div class="grid gap-1.5">
                <Label for="table-name">Table name</Label>
                <Input
                  id="table-name"
                  :model-value="plan.selected.value.label"
                  maxlength="24"
                  placeholder="A1"
                  @update:model-value="plan.update(plan.selected.value!.id, { label: String($event) })"
                />
              </div>
              <div class="grid gap-1.5">
                <Label for="table-seats">Seats</Label>
                <Input
                  id="table-seats"
                  type="number"
                  min="0"
                  max="40"
                  :model-value="plan.selected.value.seats"
                  @update:model-value="plan.update(plan.selected.value!.id, { seats: Number($event) || 0 })"
                />
              </div>
            </template>

            <div v-else-if="plan.selected.value.kind === 'text'" class="grid gap-1.5">
              <Label for="element-text">Text</Label>
              <Input
                id="element-text"
                :model-value="plan.selected.value.text"
                maxlength="80"
                placeholder="Terrace"
                @update:model-value="plan.update(plan.selected.value!.id, { text: String($event) })"
              />
            </div>

            <p v-else class="text-sm text-muted-foreground">
              A wall or a counter. Drag it into place; nothing is ordered from it.
            </p>

            <p class="text-xs text-muted-foreground">
              Drag to move, or pull the corner to resize. Delete removes it.
            </p>
          </div>
        </template>
      </aside>

      <!-- Canvas. Capped so Save and Discard stay on screen: the room is 800 units tall
           and would otherwise push the only two decisions in the dialog below the fold. -->
      <FloorPlanCanvas
        frame-class="max-h-[calc(92vh-19rem)] min-h-64"
        :elements="plan.elements.value"
        :width="plan.width.value"
        :height="plan.height.value"
        :selected-id="plan.selectedId.value"
        @select="plan.selectedId.value = $event"
        @place="plan.place"
      />
    </div>

    <!-- Commit --------------------------------------------------------------- -->
    <div class="flex flex-wrap items-center justify-between gap-3 border-t border-border pt-4">
      <p
        class="text-sm"
        :class="plan.problem.value ? 'text-destructive' : 'text-muted-foreground'"
      >
        <template v-if="plan.problem.value">{{ plan.problem.value }}</template>
        <template v-else-if="plan.dirty.value">
          Unsaved changes. Closing keeps them; only Save writes them.
        </template>
        <template v-else>Nothing to save yet.</template>
      </p>
      <div class="flex items-center gap-2">
        <Button variant="ghost" size="sm" @click="emit('close')">Close</Button>
        <Button
          variant="outline"
          size="sm"
          :disabled="!plan.dirty.value"
          @click="plan.discard"
        >
          Discard changes
        </Button>
        <Button
          size="sm"
          :disabled="!plan.dirty.value || plan.saving.value || Boolean(plan.problem.value)"
          @click="onSave"
        >
          <FontAwesomeIcon
            v-if="plan.saving.value"
            :icon="['fas', 'spinner']"
            class="motion-safe:animate-spin"
          />
          Save floor plan
        </Button>
      </div>
    </div>
  </div>
</template>
