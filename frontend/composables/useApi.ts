import type { AgentListResponse, AgentRequest, AgentResponse, HealthResponse } from '~/types/api'

/**
 * Typed wrapper around the `$api` plugin instance. One function per backend
 * endpoint (see CONTRACT §4); every function rejects with an `ApiError`.
 */
export function useApi() {
  const { $api } = useNuxtApp()

  return {
    /** GET /api/health */
    health: (): Promise<HealthResponse> => $api<HealthResponse>('/health'),

    /** GET /api/agents */
    listAgents: (): Promise<AgentListResponse> => $api<AgentListResponse>('/agents'),

    /** POST /api/agents/run */
    runAgent: (body: AgentRequest): Promise<AgentResponse> =>
      $api<AgentResponse>('/agents/run', { method: 'POST', body }),
  }
}
