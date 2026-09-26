<script setup lang="ts">
/**
 * The picture beside a dish - or, when the restaurant has not taken one, a stand-in.
 *
 * Every row gets a square, so the menu keeps its rhythm whether or not the kitchen has
 * been photographed. The stand-in is drawn inline (a plate on a warm cloth, tinted by
 * diet) rather than fetched: it costs nothing, never 404s, and reads as "no photo yet"
 * rather than "broken".
 */
defineProps<{ src: string, diet: string, alt?: string }>()

function tint(diet: string): { cloth: string, rim: string } {
  if (diet === 'veg') {
    return { cloth: '#dcefdc', rim: '#7fb77e' }
  }
  if (diet === 'non-veg') {
    return { cloth: '#f6e0d6', rim: '#d98c74' }
  }
  return { cloth: '#f1e7d4', rim: '#cdb48a' }
}
</script>

<template>
  <img
    v-if="src"
    :src="src"
    :alt="alt ?? ''"
    loading="lazy"
    class="aspect-square w-24 rounded-xl object-cover"
  >
  <svg
    v-else
    viewBox="0 0 96 96"
    class="aspect-square w-24 rounded-xl"
    role="img"
    aria-label="No photo yet"
  >
    <defs>
      <linearGradient :id="`cloth-${diet || 'any'}`" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0" :stop-color="tint(diet).cloth" />
        <stop offset="1" stop-color="#ffffff" stop-opacity="0.35" />
      </linearGradient>
    </defs>
    <rect width="96" height="96" :fill="tint(diet).cloth" />
    <rect width="96" height="96" :fill="`url(#cloth-${diet || 'any'})`" />
    <!-- the plate -->
    <circle cx="48" cy="50" r="27" fill="#ffffff" :stroke="tint(diet).rim" stroke-width="2" />
    <circle cx="48" cy="50" r="19" fill="none" :stroke="tint(diet).rim" stroke-width="1" opacity="0.6" />
    <!-- what is on it -->
    <ellipse cx="48" cy="50" rx="11" ry="8" :fill="tint(diet).rim" opacity="0.55" />
    <circle cx="43" cy="47" r="2.2" fill="#ffffff" opacity="0.8" />
    <circle cx="52" cy="52" r="1.6" fill="#ffffff" opacity="0.8" />
    <!-- fork and knife -->
    <path d="M14 30v34M11 30v10a3 3 0 0 0 6 0V30" fill="none" :stroke="tint(diet).rim" stroke-width="2" stroke-linecap="round" />
    <path d="M82 30v34M82 30c-4 4-4 14 0 18" fill="none" :stroke="tint(diet).rim" stroke-width="2" stroke-linecap="round" />
  </svg>
</template>
