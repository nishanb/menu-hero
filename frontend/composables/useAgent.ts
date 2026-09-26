import type { ChatMessage } from '~/types/chat'
import { toApiError } from '~/utils/api-error'

export const DEFAULT_AGENT = 'example'

let counter = 0
function createId(): string {
  counter += 1
  return `${Date.now().toString(36)}-${counter.toString(36)}-${Math.random().toString(36).slice(2, 6)}`
}

function createMessage(role: ChatMessage['role'], content: string, extra: Partial<ChatMessage> = {}): ChatMessage {
  return {
    id: createId(),
    role,
    content,
    status: 'done',
    createdAt: new Date().toISOString(),
    ...extra,
  }
}

/**
 * Chat state for the agent page. State lives in `useState` so it survives
 * client-side navigation between pages and is shared by every component that
 * calls `useAgent()`.
 */
export function useAgent() {
  const api = useApi()

  const messages = useState<ChatMessage[]>('agent:messages', () => [])
  const isRunning = useState<boolean>('agent:isRunning', () => false)
  const error = useState<string | null>('agent:error', () => null)
  const selectedAgent = useState<string>('agent:selectedAgent', () => DEFAULT_AGENT)

  function patchMessage(id: string, patch: Partial<ChatMessage>): void {
    messages.value = messages.value.map(message => (message.id === id ? { ...message, ...patch } : message))
  }

  /**
   * Send `message` to the selected agent (or `agent`, when given). Empty input and
   * calls made while another run is in flight are ignored.
   */
  async function runAgent(message: string, agent?: string): Promise<void> {
    const text = message.trim()
    if (!text || isRunning.value) return

    const agentName = agent ?? selectedAgent.value
    isRunning.value = true
    error.value = null

    messages.value = [
      ...messages.value,
      createMessage('user', text),
      createMessage('agent', '', { agent: agentName, status: 'pending' }),
    ]
    const pendingId = messages.value[messages.value.length - 1]!.id

    try {
      const result = await api.runAgent({ message: text, agent: agentName })
      patchMessage(pendingId, {
        content: result.response,
        agent: result.agent,
        status: 'done',
        metadata: result.metadata,
      })
    } catch (caught) {
      const apiError = toApiError(caught)
      error.value = apiError.displayMessage
      patchMessage(pendingId, { content: apiError.displayMessage, status: 'error' })
    } finally {
      isRunning.value = false
    }
  }

  /** Clear the transcript and any error. Does not change the selected agent. */
  function reset(): void {
    messages.value = []
    error.value = null
    isRunning.value = false
  }

  return { messages, isRunning, error, selectedAgent, runAgent, reset }
}
