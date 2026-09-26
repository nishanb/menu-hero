import { fetchSession, useSessionState } from '~/composables/useSession'

/**
 * Re-check the session when a page comes back from the back/forward cache.
 *
 * A bfcache restore hands back the whole JS heap — no page load, no route middleware, no
 * hydration — so nothing else in the app gets a chance to notice that the session changed
 * while the page sat in the cache. Signing out and pressing Back would otherwise show the
 * dashboard, fully interactive, to someone who is signed out.
 *
 * Only a change forces a reload: the common case (still signed in) costs one request and
 * leaves the page exactly as it was.
 */
export default defineNuxtPlugin((nuxtApp) => {
  window.addEventListener('pageshow', (event) => {
    if (!event.persisted) {
      return
    }
    nuxtApp.runWithContext(() => {
      const was = useSessionState().value?.authenticated === true
      return fetchSession(true)
        .then((session) => {
          if (session.authenticated !== was) {
            // A full load re-runs the server-side redirect, so the person lands wherever
            // their new state belongs rather than on a page this one has to patch up.
            reloadNuxtApp({ persistState: false })
          }
        })
        // A failed check is not evidence of anything; leave the page alone.
        .catch(() => {})
    })
  })
})
