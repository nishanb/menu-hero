import type { LogoutResponse, SessionState } from '~/types/api'

/** Payload key: the session rendered on the server hydrates without a flash of "signed out". */
const SESSION_KEY = 'mh-session'

/** Where a signed-in person lands when they have not asked for anywhere in particular. */
export const HOME_PATH = '/dashboard'

/** Where a signed-out person is sent. */
export const LOGIN_PATH = '/login'

/**
 * Reactive sign-in state, shared by every component and by the route middleware.
 *
 * `null` means "not looked up yet" — distinct from `{ authenticated: false }`, which is a
 * checked answer. The global middleware fills it on the first navigation, so components can
 * read it synchronously.
 */
export function useSessionState() {
  return useState<SessionState | null>(SESSION_KEY, () => null)
}

/**
 * The signed-in profile, or `null`. Read-only view for components.
 */
export function useSession() {
  const state = useSessionState()
  return {
    state,
    user: computed(() => (state.value?.authenticated ? state.value.user : null)),
    role: computed(() => (state.value?.authenticated ? state.value.effective_role : null)),
    memberships: computed(() => (state.value?.authenticated ? state.value.memberships : [])),
    isAuthenticated: computed(() => state.value?.authenticated === true),
  }
}

/**
 * Per page load in the browser (module state is re-created on every full load, and this is
 * never read on the server). See `mustVerify` below.
 */
let verifiedThisLoad = false

/**
 * Look the session up once and cache it; `force` re-checks (after signing out, or after a
 * role change that should bite immediately).
 *
 * `useRequestFetch()` rather than plain `$fetch`: during SSR the incoming request's cookies
 * have to be forwarded to `/session`, otherwise every server-rendered page would decide
 * nobody is signed in and bounce a perfectly valid session to the login screen.
 *
 * The browser re-checks once per page load instead of trusting the session serialised into
 * the HTML it was handed. That HTML is not necessarily fresh - the service worker can replay
 * a precached copy of `/` - and a page that says "signed in" because it was rendered for
 * someone who was is the one wrong answer that matters. The cached value stays in place
 * while the check is in flight, so nothing flickers. A back/forward-cache restore runs no
 * middleware at all, so it is handled separately, in `plugins/session.client.ts`.
 *
 * The in-flight promise is parked on `nuxtApp` (one instance per request on the server, so
 * it cannot leak between users) to collapse concurrent callers into a single lookup.
 */
export async function fetchSession(force = false): Promise<SessionState> {
  const state = useSessionState()
  const mustVerify = import.meta.client && !verifiedThisLoad
  if (mustVerify) {
    verifiedThisLoad = true
  }
  if (state.value && !force && !mustVerify) {
    return state.value
  }

  const nuxtApp = useNuxtApp() as { _mhSession?: Promise<SessionState> }
  if (!nuxtApp._mhSession || force) {
    const request = useRequestFetch()
    const pending: Promise<SessionState> = request<SessionState>('/session')
      .then((session) => {
        state.value = session
        return session
      })
      .finally(() => {
        // Only clear our own: a `force` call may already have replaced it.
        if (nuxtApp._mhSession === pending) {
          delete nuxtApp._mhSession
        }
      })
    nuxtApp._mhSession = pending
  }
  return nuxtApp._mhSession
}

/**
 * Revoke the session and return to the login page.
 *
 * The cookie is `HttpOnly`, so only the backend can clear it; the local state is dropped
 * either way, because a logout that fails server-side must not leave the UI showing a
 * signed-in shell.
 */
export async function signOut(): Promise<void> {
  const state = useSessionState()
  try {
    await $fetch<LogoutResponse>('/api/v1/auth/logout', { method: 'POST' })
  }
  finally {
    state.value = { authenticated: false }
    await navigateTo(LOGIN_PATH, { replace: true })
  }
}
