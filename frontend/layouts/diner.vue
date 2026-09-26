<script setup lang="ts">
/**
 * The diner's shell: a phone, held in one hand, at a table.
 *
 * Nothing of the management app belongs here - no rail, no session, no restaurant
 * switcher - and nothing of the desktop either. The page is a single column that reads
 * top to bottom and reaches the thumb: what is sticky is sticky because a thumb cannot
 * scroll back up to find it. Safe-area padding keeps the bottom bar above the home
 * indicator on the phones that have one.
 */
useHead({
  meta: [
    { name: 'viewport', content: 'width=device-width, initial-scale=1, viewport-fit=cover' },
  ],
})
</script>

<template>
  <div class="mx-auto min-h-dvh w-full max-w-md bg-background text-foreground">
    <slot />
  </div>
</template>
