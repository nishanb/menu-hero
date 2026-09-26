<script setup lang="ts">
/**
 * Getting an existing menu into MenuHero.
 *
 * A POS item export as CSV, for now — the front of the ingestion pipeline in HLD 3.2 and
 * 9.1, and the reason a restaurant does not have to retype a menu it already has. Photos and
 * PDFs are the same doorway later; what they all share is that a person reads the result
 * before it becomes the menu.
 */
const { active, canManageActive, hasLoaded } = useRestaurants()

definePageMeta({ layout: 'app' })

useHead({ title: 'Import menu' })
</script>

<template>
  <div class="mx-auto w-full max-w-3xl px-5 pt-[5vh] pb-20">
    <header class="mb-6">
      <h1 class="text-[1.6rem] leading-tight font-normal tracking-[-0.02em]">Import menu</h1>
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

    <MenuImport v-else :tenant-id="active.id" :can-manage="canManageActive" />
  </div>
</template>
