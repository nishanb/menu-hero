/**
 * Catch-all proxy for `/api/*`.
 *
 * The browser (and Nuxt's own server-side rendering) only ever talks to
 * same-origin `/api/...`. This Nitro route forwards those requests to the FastAPI
 * backend at `runtimeConfig.apiProxyTarget` (env: NUXT_API_PROXY_TARGET), which is
 * what makes `/api/*` work without nginx in:
 *
 *   - `nuxi dev`         → http://127.0.0.1:8000 (uvicorn on the same machine)
 *   - docker-compose     → http://backend:8000   (the backend service)
 *   - SSR                → any `$fetch('/api/...')` executed on the server
 *
 * In the production image nginx routes `/api/` straight to FastAPI, so this
 * handler is only reached there for SSR-time fetches.
 *
 * `proxyRequest` (h3) forwards the method, headers and body, keeps the query
 * string (`event.path` includes it) and streams the upstream status, headers and
 * body back unchanged — so FastAPI's 404/422/500/504 JSON reaches the client as is.
 * If the backend cannot be reached, h3 answers 502 Bad Gateway.
 *
 * `redirect: 'manual'` is what makes the Google sign-in work. By default the proxy's
 * own fetch *follows* a 3xx, so the browser would receive the followed page's body
 * with a 200 instead of the redirect — and the `Set-Cookie` that
 * `/api/v1/auth/google/callback` sends alongside its 302 would be consumed here
 * instead of reaching the browser, leaving the user signed out on every attempt.
 * Relaying 3xx untouched is also what the paragraph above claims. Production is
 * unaffected: nginx sends `/api/` straight to FastAPI and never follows redirects.
 */
export default defineEventHandler((event) => {
  const { apiProxyTarget } = useRuntimeConfig(event)
  const base = apiProxyTarget.replace(/\/+$/, '')
  return proxyRequest(event, `${base}${event.path}`, {
    fetchOptions: { redirect: 'manual' },
  })
})
