/**
 * The session gate. Runs on every navigation, server-side and client-side.
 *
 *   signed out  ->  /login (with `?next=` so sign-in returns to where they were heading)
 *   signed in   ->  /dashboard, for `/` and for the login page
 *
 * Public routes are listed explicitly rather than inferred: adding a page should not
 * accidentally open a hole, so anything not named below needs a session.
 */
import { HOME_PATH, LOGIN_PATH, fetchSession } from '~/composables/useSession'

/** Reachable while signed out. `/invite` is here because the invitee signs in *from* it. */
const PUBLIC_PATHS = new Set([LOGIN_PATH, '/invite'])

/**
 * Whole trees reachable while signed out. `/restaurant/...` is the diner's side - the page
 * behind the QR code on the table - and a diner has no account to sign in with.
 */
const PUBLIC_PREFIXES = ['/restaurant/']

/** Only same-origin paths, and never the login page itself (that would bounce forever). */
function safeNext(value: unknown): string | null {
  if (typeof value !== 'string' || !value.startsWith('/') || value.startsWith('//')) {
    return null
  }
  return value === LOGIN_PATH || value.startsWith(`${LOGIN_PATH}?`) ? null : value
}

export default defineNuxtRouteMiddleware(async (to) => {
  // `/dashboard/` and `/dashboard` are the same route to a person; treat them the same
  // here too, so a trailing slash cannot slip past the public-path check.
  const path = to.path.length > 1 ? to.path.replace(/\/+$/, '') : to.path

  // The backend's per-role portal paths (/admin, /owner, /staff, /app) are redirected to
  // the dashboard by `router.options.ts`, before this runs - so `to` is already the real
  // destination and `next=` records a path that will still exist after signing in.
  const session = await fetchSession()

  if (path === LOGIN_PATH) {
    if (!session.authenticated) {
      return
    }
    return navigateTo(safeNext(to.query.next) ?? HOME_PATH, { replace: true })
  }

  if (path === '/') {
    return navigateTo(session.authenticated ? HOME_PATH : LOGIN_PATH, { replace: true })
  }

  if (PUBLIC_PATHS.has(path) || PUBLIC_PREFIXES.some(prefix => path.startsWith(prefix))) {
    return
  }

  if (!session.authenticated) {
    return navigateTo({ path: LOGIN_PATH, query: { next: to.fullPath } }, { replace: true })
  }
})
