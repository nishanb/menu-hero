<script setup lang="ts">
/**
 * The QR codes that point a diner at this restaurant's menu.
 *
 * Tables come from the floor plan (Settings → Floor Plan), which is why a table is an
 * identity that outlives the drawing: a code printed today has to still resolve after the
 * room is rearranged. See `backend/app/models/table.py`.
 *
 * Nothing is built here yet — see `pages/menus/index.vue` for why the page exists anyway.
 */
const { active, hasLoaded } = useRestaurants()

definePageMeta({ layout: 'app' })

useHead({ title: 'Table QR code' })
</script>

<template>
  <div class="mx-auto w-full max-w-5xl px-5 pt-[5vh] pb-20 print:max-w-none print:p-0">
    <header class="mb-6 print:hidden">
      <h1 class="text-[1.6rem] leading-tight font-normal tracking-[-0.02em]">Table QR code</h1>
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

    <TableQrCodes v-else :tenant-id="active.id" />
  </div>
</template>
