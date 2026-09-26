<script setup lang="ts">
const props = withDefaults(defineProps<{ disabled?: boolean; placeholder?: string }>(), {
  disabled: false,
  placeholder: 'Type your message...',
})

const emit = defineEmits<{ send: [message: string] }>()

const inputId = useId()
const text = ref('')
const textarea = ref<HTMLTextAreaElement | null>(null)

const rows = computed(() => Math.min(6, Math.max(1, text.value.split('\n').length)))
const canSend = computed(() => !props.disabled && text.value.trim().length > 0)

function submit(): void {
  if (!canSend.value) return
  emit('send', text.value)
  text.value = ''
}

/** Enter sends; Shift+Enter (handled by the browser) inserts a newline. */
function onEnter(event: KeyboardEvent): void {
  if (event.isComposing) return
  event.preventDefault()
  submit()
}

function focus(): void {
  textarea.value?.focus()
}

defineExpose({ focus })
</script>

<template>
  <form class="chat-input" @submit.prevent="submit">
    <label :for="inputId" class="sr-only">Message</label>
    <textarea
      :id="inputId"
      ref="textarea"
      v-model="text"
      class="chat-input__field"
      :rows="rows"
      :placeholder="placeholder"
      :disabled="disabled"
      autocomplete="off"
      @keydown.enter.exact="onEnter"
    />
    <button
      type="submit"
      class="btn btn--primary chat-input__send"
      :disabled="!canSend"
      aria-label="Send message"
      title="Send (Enter)"
    >
      &rarr;
    </button>
  </form>
</template>

<style scoped>
.chat-input {
  display: flex;
  align-items: flex-end;
  gap: var(--space-2);
}

.chat-input__field {
  flex: 1;
  resize: none;
  min-height: 2.75rem;
  max-height: 12rem;
}

.chat-input__send {
  width: 2.75rem;
  height: 2.75rem;
  padding: 0;
  font-size: 1.25rem;
  flex-shrink: 0;
}
</style>
