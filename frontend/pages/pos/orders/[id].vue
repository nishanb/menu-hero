<script setup lang="ts">
/**
 * One order on the POS. The id in the route is the order's; the restaurant is the active one.
 */
const route = useRoute()
const { active, hasLoaded } = useRestaurants()

const orderId = computed(() => String(route.params.id ?? ''))

definePageMeta({ layout: 'pos' })

useHead({ title: 'Order' })
</script>

<template>
  <div class="flex min-h-0 flex-1 flex-col print:block">
    <Skeleton v-if="!active && !hasLoaded" class="m-3 flex-1 rounded-xl" />

    <ClientOnly v-else-if="active">
      <template #fallback>
        <Skeleton class="m-3 flex-1 rounded-xl" />
      </template>
      <PosOrder :tenant-id="active.id" :order-id="orderId" />
    </ClientOnly>
  </div>
</template>
