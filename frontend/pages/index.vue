<script setup lang="ts">
/**
 * `/` is a signpost, not a page.
 *
 * `middleware/auth.global.ts` sends every visit on to `/dashboard` or `/login` before this
 * renders, so the markup below is only ever seen if that redirect is somehow skipped — and
 * it says so rather than pretending to be a landing page.
 */
// No layout: `default.vue` is the agent demo's shell (its own nav, footer and legacy
// stylesheet), which would be an odd thing to paint around a redirect.
definePageMeta({ layout: false })

useHead({ title: 'MenuHero' })
</script>

<template>
  <div class="grid min-h-dvh place-items-center bg-background px-6 text-muted-foreground">
    <p class="text-sm">
      Taking you to MenuHero…
      <NuxtLink to="/login" class="underline underline-offset-4 hover:text-foreground">
        Sign in
      </NuxtLink>
    </p>
  </div>
</template>
