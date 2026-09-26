/** A single entry in the chat transcript rendered by <AgentChat>. */
export interface ChatMessage {
  id: string
  role: 'user' | 'agent'
  content: string
  /** Name of the agent that produced (or is producing) an agent message */
  agent?: string
  status: 'pending' | 'done' | 'error'
  /** ISO-8601 timestamp */
  createdAt: string
  /** `metadata` returned by the backend for a finished agent message */
  metadata?: Record<string, unknown>
}
