<script setup lang="ts">
/**
 * The sections a menu is read in: Starters, Mains, Desserts.
 *
 * Editable here rather than only at publish time, and kept apart from the items themselves,
 * because a restaurant knows the shape of its menu before it has typed a single dish in.
 * HLD 4 stores an item's section as `category_path` text on the published item — that is the
 * immutable side; this is the list an owner maintains.
 */
const { active, canManageActive, hasLoaded } = useRestaurants()

definePageMeta({ layout: 'app' })

useHead({ title: 'Categories' })
</script>

<template>
  <div class="mx-auto w-full max-w-3xl px-5 pt-[5vh] pb-20">
    <header class="mb-6">
      <h1 class="text-[1.6rem] leading-tight font-normal tracking-[-0.02em]">Categories</h1>
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

    <CategoryTable v-else :tenant-id="active.id" :can-manage="canManageActive" />
  </div>
</template>
