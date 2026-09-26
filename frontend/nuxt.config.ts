// https://nuxt.com/docs/api/configuration/nuxt-config
//
// Flat layout: this file, app.vue and the pages/, components/, composables/, layouts/,
// plugins/, assets/, public/, types/, utils/ and server/ directories all live at the
// frontend/ root (no app/ directory). Nuxt 4 uses the root as `srcDir` when app/ is
// absent, so no explicit `srcDir` is required.
import tailwindcss from '@tailwindcss/vite'

export default defineNuxtConfig({
  compatibilityDate: '2026-09-06',
  ssr: true,

  // `nuxi dev` listens on `localhost`, which Node >= 17 resolves to ::1 only on
  // macOS, so http://127.0.0.1:3000 (the address the README, the curl checks and
  // the proxy configs use) would be refused. Pin the IPv4 loopback explicitly;
  // http://localhost:3000 keeps working in browsers and curl (they fall back to
  // IPv4). Pass `--host` on the command line to override.
  devServer: {
    host: '127.0.0.1',
    port: 3000,
  },

  css: [
    '@fortawesome/fontawesome-svg-core/styles.css',
    '~/assets/css/tailwind.css',
    '~/assets/css/main.css',
  ],

  vite: {
    plugins: [tailwindcss()],
  },

  app: {
    head: {
      // Renders as "<page title> · MenuHero"; the %separator token is dropped
      // automatically on pages that set no title, leaving just "MenuHero".
      // "MenuHero" (one word) is the wordmark the marketing site uses.
      titleTemplate: '%s %separator MenuHero',
      templateParams: { separator: '·' },
      htmlAttrs: { lang: 'en' },
      link: [
        { rel: 'icon', href: '/favicon.ico', sizes: '48x48' },
        { rel: 'icon', type: 'image/svg+xml', href: '/logo.svg' },
        // iOS ignores the manifest's icons for the home screen; it reads this.
        { rel: 'apple-touch-icon', href: '/apple-touch-icon-180x180.png' },
      ],
      meta: [
        { name: 'viewport', content: 'width=device-width, initial-scale=1' },
        { name: 'apple-mobile-web-app-title', content: 'MenuHero' },
        {
          name: 'description',
          content:
            'MenuHero — a Nuxt 4 front end for a FastAPI service that runs a pluggable AI agent system.',
        },
      ],
    },
  },

  // Runtime config. Every key can be overridden at runtime (no rebuild) with an
  // environment variable — see https://nuxt.com/docs/guide/going-further/runtime-config
  //
  //   apiProxyTarget  → NUXT_API_PROXY_TARGET   (server-only; where server/api/[...].ts forwards /api/*)
  //   public.apiBase  → NUXT_PUBLIC_API_BASE    (exposed to the browser; base URL used by the $api plugin)
  //   public.appName  → NUXT_PUBLIC_APP_NAME    (exposed to the browser)
  //
  // The browser always talks to same-origin `public.apiBase` (/api); only the Nitro
  // server knows the backend address. This is the only place the backend address
  // (127.0.0.1:8000) may appear in the code base.
  runtimeConfig: {
    apiProxyTarget: 'http://127.0.0.1:8000',
    // Name of the backend's session cookie (backend: `SESSION_COOKIE_NAME`). `GET /session`
    // uses it to answer "signed out" without a round trip when the cookie is absent; if the
    // two ever disagree the only cost is a wasted call that returns 401, never a wrong answer.
    sessionCookieName: 'mh_session',
    public: {
      apiBase: '/api',
      appName: 'MenuHero',
    },
  },

  // The backend hands every role its own landing path (`backend/app/models/roles.py:
  // PORTAL_PATHS`) and the Google callback redirects the browser straight there. Until
  // those portals are separate pages they all resolve to the one dashboard - without this a
  // successful sign-in ends on a 404.
  //
  // Done here rather than in `middleware/auth.global.ts` so Nitro answers with a redirect
  // before Nuxt renders anything: route middleware runs *after* the router has tried to
  // match, so an unmatched `/app` also logs a "No match found" warning on every sign-in.
  routeRules: {
    '/admin': { redirect: '/dashboard' },
    '/owner': { redirect: '/dashboard' },
    '/staff': { redirect: '/dashboard' },
    '/app': { redirect: '/dashboard' },
  },

  // Auto-import the shadcn components: `<Button>` rather than an import in every file.
  // `nuxi module add` registers the module but writes no options, and without these the
  // components silently resolve to nothing (Vue warns, the element renders empty).
  shadcn: {
    prefix: '',
    componentDir: '@/components/ui',
  },

  // shadcn's dark variant is `&:is(.dark *)`, so the class on <html> must be exactly
  // `dark` — the module's default would write `dark-mode` and nothing would theme.
  colorMode: {
    classSuffix: '',
  },

  // Progressive web app. The management app is used on a phone at the pass, so it has
  // to install to the home screen and survive a flaky connection.
  pwa: {
    registerType: 'autoUpdate',
    manifest: {
      name: 'MenuHero',
      short_name: 'MenuHero',
      description: 'MenuHero — menus, orders and the kitchen board.',
      lang: 'en',
      start_url: '/',
      scope: '/',
      display: 'standalone',
      background_color: '#f5f6f8',
      theme_color: '#172033',
      icons: [
        { src: 'pwa-64x64.png', sizes: '64x64', type: 'image/png' },
        { src: 'pwa-192x192.png', sizes: '192x192', type: 'image/png' },
        { src: 'pwa-512x512.png', sizes: '512x512', type: 'image/png' },
        {
          src: 'maskable-icon-512x512.png',
          sizes: '512x512',
          type: 'image/png',
          purpose: 'maskable',
        },
      ],
    },
    workbox: {
      globPatterns: ['**/*.{js,css,html,svg,png,ico,woff2}'],
      // No SPA navigation fallback. @vite-pwa/nuxt otherwise defaults this to '/' and emits
      // `createHandlerBoundToURL('/')`, which throws while the worker is evaluating because
      // an SSR build precaches no HTML at all - the worker then fails to install and the app
      // is not installable in production. Declaring the key (even as undefined) is what
      // stops the module filling it in. Navigations therefore always reach Nitro, which is
      // what an SSR app with sessions wants: no cached shell can answer for `/`.
      navigateFallback: undefined,
      // Without this the service worker answers /api/* navigations with the SPA shell.
      // `GET /api/v1/auth/google` and its callback are top-level navigations, so Google
      // sign-in would break in production only — where the worker is registered — and
      // look like a redirect loop rather than a caching bug.
      // `/session` is listed too: it is fetched, not navigated, so the fallback would not
      // catch it anyway - but it must never be precached or served from the cache either,
      // or the app could boot offline believing a stale sign-in state.
      navigateFallbackDenylist: [/^\/api\//, /^\/session$/],
    },
    // On in dev too, otherwise there is no registered service worker and the browser
    // never offers to install the app - a manifest on its own is not enough for Chrome's
    // install criteria, which is the usual reason a PWA "does not work" in `nuxi dev`.
    //
    // `navigateFallback` is deliberately NOT set. It used to be '/', which made the dev
    // worker precache `/` and answer every visit to it from that copy. `/` is now an
    // auth-dependent redirect, so the cached copy was whatever the *last* person to install
    // the worker saw - the signed-in dashboard, still served after signing out. Precaching a
    // page whose content depends on a session is a soundness bug, not a tuning knob.
    devOptions: {
      enabled: true,
      suppressWarnings: true,
      type: 'module',
      // An empty allowlist means the worker never answers a navigation from its cache.
      // The default is `navigateFallback: '/'`, which precaches `/` and replays it - and `/`
      // is now an auth-dependent redirect, so the cached copy was whoever installed the
      // worker last: the signed-in dashboard, still served after signing out.
      navigateFallbackAllowlist: [],
    },
  },

  typescript: {
    strict: true,
    // Type checking is a separate step (`npm run typecheck`) so `nuxi dev`/`build` stay fast.
    typeCheck: false,
  },

  modules: ['shadcn-nuxt', '@vite-pwa/nuxt', '@nuxtjs/color-mode'],
})