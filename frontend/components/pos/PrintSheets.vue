<script setup lang="ts">
/**
 * Where a ticket or a bill is rendered for the printer. See `usePosPrinter`.
 *
 * Hidden on screen, the only visible thing in print: the unscoped rule below hides
 * everything in the body and then un-hides this, which is the one way to print a piece of
 * a page that lives inside a layout without printing the layout.
 */
import type { PrintJob } from '~/composables/usePosPrinter'

defineProps<{ job: PrintJob | null }>()

const { active } = useRestaurants()

const restaurant = computed(() => active.value?.detail)
const restaurantName = computed(() => active.value?.name ?? '')
</script>

<template>
  <div class="print-sheets hidden print:block">
    <PosKotTicket v-if="job?.kind === 'kot'" :kot="job.kot" :restaurant="restaurantName" />
    <PosBillReceipt
      v-else-if="job?.kind === 'bill'"
      :order="job.order"
      :restaurant="restaurant"
      :name="restaurantName"
    />
  </div>
</template>

<!-- Unscoped for the same reason as the other print pages: it has to reach `body *`. -->
<style>
@media print {
  body * {
    visibility: hidden;
  }

  .print-sheets,
  .print-sheets * {
    visibility: visible;
  }

  .print-sheets {
    position: absolute;
    top: 0;
    left: 0;
  }
}
</style>
