<script setup lang="ts">
/**
 * The menu as a sheet of paper, in four layouts.
 *
 * Printed by the browser rather than rendered to PDF server-side — see `PhysicalMenu.vue`
 * for why that produces the better document.
 */
const { active, hasLoaded } = useRestaurants()

definePageMeta({ layout: 'app' })

useHead({ title: 'Physical menu' })
</script>

<template>
  <div class="mx-auto w-full max-w-6xl px-5 pt-[5vh] pb-20 print:max-w-none print:p-0">
    <header class="mb-6 print:hidden">
      <h1 class="text-[1.6rem] leading-tight font-normal tracking-[-0.02em]">Physical menu</h1>
      <p v-if="active" class="mt-1 text-sm text-muted-foreground">
        {{ active.name }}
        <span class="font-mono text-xs">· {{ active.slug }}</span>
      </p>
    </header>

    <!-- Still finding out. A platform admin holds no memberships, so the session alone says
         nothing about which restaurants they can see. -->
    <Skeleton v-if="!active && !hasLoaded" class="h-40 w-full rounded-xl" />

    <!-- No restaurant at all: a menu has nothing to belong to. -->
    <section
      v-else-if="!active"
      class="rounded-xl border border-dashed border-border px-6 py-12 text-center"
    >
      <p class="text-sm text-muted-foreground">
        There is no restaurant to build a menu for yet.
      </p>
      <Button class="mt-4" as-child>
        <NuxtLink to="/onboarding">Set up a restaurant</NuxtLink>
      </Button>
    </section>

    <PhysicalMenu v-else :tenant-id="active.id" />
  </div>
</template>
