<script setup lang="ts">
/**
 * Menu management: the items a diner reads and orders from.
 *
 * Wider than the other pages because it is a two-pane workspace — sections down the left,
 * dishes on the right — and a 3xl column would letterbox the table.
 */
const { active, canManageActive, hasLoaded } = useRestaurants()

definePageMeta({ layout: 'app' })

useHead({ title: 'Menu' })
</script>

<template>
  <div class="mx-auto w-full max-w-6xl px-5 pt-[5vh] pb-20">
    <header class="mb-6">
      <h1 class="text-[1.6rem] leading-tight font-normal tracking-[-0.02em]">Menu</h1>
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

    <MenuItems v-else :tenant-id="active.id" :can-manage="canManageActive" />
  </div>
</template>
