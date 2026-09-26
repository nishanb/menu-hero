import { ApiError } from '~/utils/api-error'

/**
 * Provides `$api`: a pre-configured `$fetch` instance for the backend.
 *
 * - `baseURL` comes from `runtimeConfig.public.apiBase` (default `/api`, env
 *   NUXT_PUBLIC_API_BASE). Requests are same-origin; in dev/SSR/docker-compose the
 *   Nitro catch-all in server/api/[...].ts forwards them to FastAPI, and in the
 *   production image nginx does.
 * - Every non-2xx response is turned into an `ApiError` carrying the HTTP status
 *   and FastAPI's `detail`, so callers can `catch (e) { if (e instanceof ApiError) ... }`.
 */
export default defineNuxtPlugin({
  name: 'menu-hero-api',
  setup() {
    const config = useRuntimeConfig()

    const api = $fetch.create({
      baseURL: config.public.apiBase,
      headers: { Accept: 'application/json' },
      // Errors are surfaced as ApiError; no silent retries against the agent endpoints.
      retry: 0,
      onResponseError({ response }) {
        throw ApiError.fromResponse(response.status, response._data)
      },
    })

    return {
      provide: { api },
    }
  },
})
