<script setup lang="ts">
import type { AgentInfo } from '~/types/api'
import { DEFAULT_AGENT } from '~/composables/useAgent'

const api = useApi()
const { messages, isRunning, error, selectedAgent, runAgent, reset } = useAgent()

// Available agents, loaded on the client. If the request fails we silently keep
// the default agent so the chat still works.
const FALLBACK_AGENTS: AgentInfo[] = [{ name: DEFAULT_AGENT, description: 'Example agent' }]

const { data: agentList } = useAsyncData('agent-list', () => api.listAgents(), {
  server: false,
  lazy: true,
})

const agents = computed<AgentInfo[]>(() =>
  agentList.value?.agents?.length ? agentList.value.agents : FALLBACK_AGENTS,
)

watch(agents, (list) => {
  if (!list.some(agent => agent.name === selectedAgent.value)) {
    selectedAgent.value = list[0]?.name ?? DEFAULT_AGENT
  }
})

const selectedDescription = computed(
  () => agents.value.find(agent => agent.name === selectedAgent.value)?.description ?? '',
)

// Auto-scroll to the newest message whenever one is added or changes state.
const listEl = ref<HTMLElement | null>(null)
const inputEl = ref<{ focus: () => void } | null>(null)

const lastMessageKey = computed(() => {
  const last = messages.value[messages.value.length - 1]
  return last ? `${last.id}:${last.status}` : ''
})

watch(lastMessageKey, async () => {
  await nextTick()
  const el = listEl.value
  if (el) el.scrollTop = el.scrollHeight
})

async function send(text: string): Promise<void> {
  await runAgent(text)
  await nextTick()
  inputEl.value?.focus()
}

function dismissError(): void {
  error.value = null
}
</script>

<template>
  <section class="chat card" aria-labelledby="chat-title">
    <header class="chat__header">
      <div class="chat__heading">
        <h1 id="chat-title" class="chat__title">AI Agent</h1>
        <p v-if="selectedDescription" class="chat__subtitle">{{ selectedDescription }}</p>
      </div>
      <div class="chat__tools">
        <label class="chat__agent">
          <span class="sr-only">Agent</span>
          <select v-model="selectedAgent" :disabled="isRunning" aria-label="Agent">
            <option v-for="agent in agents" :key="agent.name" :value="agent.name">
              {{ agent.name }}
            </option>
          </select>
        </label>
        <button
          v-if="messages.length"
          type="button"
          class="btn btn--ghost"
          :disabled="isRunning"
          @click="reset"
        >
          Clear
        </button>
      </div>
    </header>

    <ul ref="listEl" class="chat__messages" aria-live="polite" :aria-busy="isRunning">
      <li v-if="messages.length === 0" class="chat__empty">
        <strong>No messages yet.</strong>
        Ask the agent something below — Enter sends, Shift+Enter adds a new line.
      </li>
      <ChatMessage v-for="message in messages" :key="message.id" :message="message" />
    </ul>

    <p v-if="error" class="chat__error" role="alert">
      <span>{{ error }}</span>
      <button type="button" class="btn btn--ghost btn--sm" @click="dismissError">Dismiss</button>
    </p>

    <ChatInput ref="inputEl" :disabled="isRunning" @send="send" />
  </section>
</template>

<style scoped>
.chat {
  width: 100%;
  max-width: 44rem;
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  min-height: min(70vh, 40rem);
}

.chat__header {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-3);
  padding-bottom: var(--space-3);
  border-bottom: 1px solid var(--mh-border);
}

.chat__heading {
  display: grid;
  gap: 0.15rem;
}

.chat__title {
  margin: 0;
  font-size: 1.35rem;
  letter-spacing: -0.02em;
}

.chat__subtitle {
  margin: 0;
  font-size: 0.85rem;
  color: var(--color-text-muted);
}

.chat__tools {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.chat__messages {
  list-style: none;
  margin: 0;
  padding: var(--space-1);
  flex: 1;
  min-height: 14rem;
  max-height: 60vh;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  scroll-behavior: smooth;
}

.chat__empty {
  margin: auto;
  padding: var(--space-4);
  text-align: center;
  color: var(--color-text-muted);
  font-size: 0.95rem;
  max-width: 28rem;
}

.chat__empty strong {
  display: block;
  color: var(--color-text);
  margin-bottom: var(--space-1);
}

.chat__error {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
  margin: 0;
  padding: var(--space-2) var(--space-3);
  border-radius: var(--mh-radius-sm);
  background: var(--color-danger-bg);
  color: var(--color-danger);
  font-size: 0.9rem;
}

@media (prefers-reduced-motion: reduce) {
  .chat__messages {
    scroll-behavior: auto;
  }
}
</style>
