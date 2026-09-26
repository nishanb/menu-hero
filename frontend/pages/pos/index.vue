<script setup lang="ts">
/**
 * The POS: the floor, and a way into every order on it.
 *
 * Open to every member. It is the floor's tool, and a server who cannot seat a table is not
 * much use — the backend agrees, so there is no owner gate anywhere under `/pos`.
 */
const { active, hasLoaded } = useRestaurants()

definePageMeta({ layout: 'pos' })

useHead({ title: 'POS' })
</script>

<template>
  <div class="flex min-h-0 flex-1 flex-col">
    <Skeleton v-if="!active && !hasLoaded" class="m-3 flex-1 rounded-xl" />

    <section
      v-else-if="!active"
      class="m-3 grid flex-1 place-items-center rounded-xl border border-dashed border-border px-6 py-12 text-center"
    >
      <div>
        <p class="text-sm text-muted-foreground">There is no restaurant to take orders for yet.</p>
        <Button class="mt-4" as-child>
          <NuxtLink to="/onboarding">Set up a restaurant</NuxtLink>
        </Button>
      </div>
    </section>

    <ClientOnly v-else>
      <template #fallback>
        <Skeleton class="m-3 flex-1 rounded-xl" />
      </template>
      <PosFloor :tenant-id="active.id" />
    </ClientOnly>
  </div>
</template>
