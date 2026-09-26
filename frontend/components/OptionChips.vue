<script setup lang="ts">
/**
 * A row of toggleable chips over an open list of options.
 *
 * "Open" is the point: `suggestions` is what the backend offers to save typing, and
 * `modelValue` may hold anything the restaurant added itself. Both are rendered, so a
 * custom option is a first-class chip rather than something hidden behind an "other" field.
 */
const props = defineProps<{
  modelValue: string[]
  suggestions: string[]
  /** Used to label the group for screen readers ("service", "diet"). */
  name: string
}>()

const emit = defineEmits<{ toggle: [option: string] }>()

/** Suggestions first, in the order the backend gave them, then anything added here. */
const chips = computed(() => [
  ...props.suggestions,
  ...props.modelValue.filter(option => !props.suggestions.includes(option)),
])

const selected = computed(() => new Set(props.modelValue))

/** `non-veg` -> `Non-veg`: stored lower-case, shown the way a person would write it. */
function label(option: string): string {
  return option.charAt(0).toUpperCase() + option.slice(1)
}
</script>

<template>
  <div
    role="group"
    :aria-label="`${name} options`"
    class="flex flex-wrap gap-2"
  >
    <button
      v-for="option in chips"
      :key="option"
      type="button"
      :aria-pressed="selected.has(option)"
      class="inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-sm transition-colors outline-hidden focus-visible:ring-2 focus-visible:ring-ring"
      :class="selected.has(option)
        ? 'border-primary bg-primary text-primary-foreground'
        : 'border-border bg-background text-foreground hover:bg-accent'"
      @click="emit('toggle', option)"
    >
      <FontAwesomeIcon
        v-if="selected.has(option)"
        :icon="['fas', 'check']"
        class="text-[0.7em]"
      />
      {{ label(option) }}
    </button>

    <p v-if="!chips.length" class="text-sm text-muted-foreground">
      Nothing chosen yet.
    </p>
  </div>
</template>
