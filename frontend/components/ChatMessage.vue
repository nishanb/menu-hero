<script setup lang="ts">
import type { ChatMessage as Message } from '~/types/chat'

const props = defineProps<{ message: Message }>()

const label = computed(() => (props.message.role === 'user' ? 'User:' : 'Agent:'))
const isPending = computed(() => props.message.status === 'pending')
const isError = computed(() => props.message.status === 'error')
</script>

<template>
  <li
    class="msg"
    :class="[`msg--${message.role}`, { 'msg--pending': isPending, 'msg--error': isError }]"
    :data-message-id="message.id"
  >
    <span class="msg__label">{{ label }}</span>
    <div class="msg__body">
      <span v-if="isPending" class="msg__pending">Processing...</span>
      <p v-else class="msg__content">{{ message.content }}</p>
      <span v-if="message.role === 'agent' && message.agent && !isPending" class="msg__meta">
        {{ isError ? 'failed' : message.agent }}
      </span>
    </div>
  </li>
</template>

<style scoped>
.msg {
  display: grid;
  grid-template-columns: 3.75rem 1fr;
  gap: var(--space-2);
  align-items: start;
  padding: var(--space-2) var(--space-3);
  border-radius: var(--mh-radius-md);
}

.msg--user {
  background: var(--color-user);
}

.msg--agent {
  background: var(--color-surface);
  border: 1px solid var(--mh-border);
}

.msg--error {
  border-color: color-mix(in srgb, var(--color-danger) 45%, var(--mh-border));
  background: var(--color-danger-bg);
}

.msg__label {
  font-weight: 600;
  font-size: 0.85rem;
  color: var(--color-text-muted);
  padding-top: 0.15rem;
}

.msg--user .msg__label {
  color: var(--mh-accent);
}

.msg__body {
  display: grid;
  gap: var(--space-1);
  min-width: 0;
}

.msg__content {
  margin: 0;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.msg--error .msg__content {
  color: var(--color-danger);
}

.msg__pending {
  color: var(--color-text-muted);
  font-style: italic;
  animation: pulse 1.2s ease-in-out infinite;
}

.msg__meta {
  font-family: var(--font-mono);
  font-size: 0.72rem;
  color: var(--color-text-muted);
}

@keyframes pulse {
  0%,
  100% {
    opacity: 0.45;
  }

  50% {
    opacity: 1;
  }
}

@media (prefers-reduced-motion: reduce) {
  .msg__pending {
    animation: none;
  }
}
</style>
