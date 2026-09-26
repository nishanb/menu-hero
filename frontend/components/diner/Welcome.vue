<script setup lang="ts">
/**
 * The first second at the table: the restaurant's name, a moment of arrival, and one
 * choice - talk, or read.
 *
 * Shown once per visit (session storage), over the menu while it loads. The animation is
 * not decoration for its own sake: the menu takes a beat to arrive, and a plate spinning
 * up under the name is a better beat than a blank page. Then two buttons, both big, both
 * honest about what they open.
 */
defineProps<{ name: string, logo: string, ready: boolean }>()

const emit = defineEmits<{ chat: [], browse: [] }>()

/** The arrival beat: long enough to read the name, never long enough to wait for. */
const ARRIVAL_MS = 1100
const arrived = ref(false)
onMounted(() => {
  window.setTimeout(() => {
    arrived.value = true
  }, ARRIVAL_MS)
})
</script>

<template>
  <div class="fixed inset-0 z-40 mx-auto flex w-full max-w-md flex-col items-center justify-center bg-background px-8 text-center">
    <div class="relative grid size-28 place-items-center">
      <!-- the plate, spinning up -->
      <span
        class="absolute inset-0 rounded-full border-[3px] border-border border-t-primary motion-safe:animate-spin"
        :class="arrived && ready ? 'opacity-0 transition-opacity duration-500' : ''"
        aria-hidden="true"
      />
      <span
        class="absolute inset-0 rounded-full border-[3px] border-primary transition-opacity duration-500"
        :class="arrived && ready ? 'opacity-100' : 'opacity-0'"
        aria-hidden="true"
      />
      <img v-if="logo" :src="logo" alt="" class="size-20 rounded-full object-cover">
      <FontAwesomeIcon v-else :icon="['fas', 'utensils']" class="text-3xl text-primary" />
    </div>

    <h1 class="mt-6 text-2xl font-semibold tracking-tight">{{ name || 'Welcome' }}</h1>
    <p class="mt-1 text-sm text-muted-foreground" aria-live="polite">
      {{ arrived && ready ? 'How would you like to order?' : 'Setting the table…' }}
    </p>

    <div
      class="mt-8 grid w-full gap-3 transition-all duration-500"
      :class="arrived && ready ? 'translate-y-0 opacity-100' : 'pointer-events-none translate-y-3 opacity-0'"
    >
      <Button class="h-14 justify-between rounded-2xl px-5 text-base" @click="emit('chat')">
        <span class="flex items-center gap-3">
          <FontAwesomeIcon :icon="['fas', 'robot']" />
          Chat &amp; order
        </span>
        <span class="text-xs font-normal opacity-80">Ask for what you feel like</span>
      </Button>
      <Button variant="outline" class="h-14 justify-between rounded-2xl px-5 text-base" @click="emit('browse')">
        <span class="flex items-center gap-3">
          <FontAwesomeIcon :icon="['fas', 'book-open']" />
          Browse the menu
        </span>
        <span class="text-xs font-normal text-muted-foreground">Sections, search, filters</span>
      </Button>
    </div>
  </div>
</template>
