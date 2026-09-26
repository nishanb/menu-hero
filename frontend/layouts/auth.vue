<script setup lang="ts">
/**
 * Bare layout for the sign-in screens.
 *
 * The default layout carries the demo Home/Agent nav and a footer, which are wrong on a
 * page whose only job is one tap. This one contributes nothing at all — the page owns its
 * own full-height canvas and background.
 */
</script>

<template>
  <slot />
</template>
