import type { MeResponse, SessionState } from '~/types/api'

/**
 * `GET /session` — who is signed in, for the browser and for SSR.
 *
 * The session cookie is `HttpOnly`, so the app cannot read it; this route is the only way
 * the UI learns whether anyone is signed in. It calls FastAPI's `/api/v1/auth/me` with the
 * caller's cookie and normalises the two ordinary outcomes into one shape:
 *
 *   signed in   -> `{ authenticated: true, user, effective_role, portal_path, memberships }`
 *   signed out  -> `{ authenticated: false }`   (401 upstream — an answer, not a failure)
 *
 * Anything else (the backend is down, the database is unreachable and answers 503) is
 * relayed as an error. Reporting a broken backend as "signed out" would bounce everyone to
 * the login page and hide the real fault behind what looks like an auth bug.
 *
 * It deliberately lives at `/session`, NOT `/api/session`: in production nginx sends every
 * `/api/` path straight to FastAPI, where a Nitro route does not exist and would 404.
 */
export default defineEventHandler(async (event): Promise<SessionState> => {
  const { apiProxyTarget, sessionCookieName } = useRuntimeConfig(event)

  // Never let a cached copy of this answer outlive the session it describes - in a
  // back/forward navigation, in a proxy, or in the service worker.
  setHeader(event, 'cache-control', 'no-store')

  const cookie = getHeader(event, 'cookie') ?? ''
  if (!new RegExp(`(?:^|;\\s*)${sessionCookieName}=`).test(cookie)) {
    return { authenticated: false }
  }

  const base = apiProxyTarget.replace(/\/+$/, '')
  const response = await $fetch.raw<MeResponse>(`${base}/api/v1/auth/me`, {
    // `$fetch` sends no cookies of its own: the caller's has to be forwarded by hand.
    headers: { cookie },
    ignoreResponseError: true,
  })

  if (response.status === 401) {
    return { authenticated: false }
  }
  if (!response.ok || !response._data) {
    throw createError({
      statusCode: 502,
      statusMessage: 'Session check failed',
      message: `The backend answered ${response.status} for /api/v1/auth/me.`,
    })
  }

  return { authenticated: true, ...response._data }
})
