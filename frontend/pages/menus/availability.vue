<script setup lang="ts">
/**
 * What is on and what is off, right now.
 *
 * Deliberately its own page rather than a column in the menu editor: taking a dish off is a
 * thing a floor manager does mid-service on a phone, not an edit to the menu. It changes what
 * a diner is offered without publishing a new version.
 *
 * Nothing is built here yet — see `pages/menus/index.vue` for why the page exists anyway.
 */
const { active, canManageActive, hasLoaded } = useRestaurants()

definePageMeta({ layout: 'app' })

useHead({ title: 'Menu on/off' })
</script>

<template>
  <div class="mx-auto w-full max-w-6xl px-5 pt-[5vh] pb-20">
    <header class="mb-6">
      <h1 class="text-[1.6rem] leading-tight font-normal tracking-[-0.02em]">Menu on/off</h1>
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

    <MenuAvailability v-else :tenant-id="active.id" :can-manage="canManageActive" />
  </div>
</template>
