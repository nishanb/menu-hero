# Menu Hero — frontend

Nuxt 4 application (SSR) that serves the Menu Hero app shell and the **AI Agent** chat UI.
The browser only ever talks to same-origin `/api/*`; the FastAPI backend is reached through a
proxy (Nitro in dev / docker-compose / SSR, nginx in the production image).

Requires Node `>= 20.19` (Node 22 LTS in Docker). No UI framework, no Tailwind — plain Vue SFCs
with a small CSS design system in `assets/css/main.css`.

## Commands

Run everything from this directory (`frontend/`).

| Command | What it does |
|---------|--------------|
| `npm install` | Install dependencies; `postinstall` runs `nuxi prepare` (generates `.nuxt/` types) |
| `npm run dev` | Dev server on http://localhost:3000 (`nuxi dev --dotenv ../.env`; the repo-root `.env` is optional) |
| `npm run build` | Production build → `.output/` (Nitro `node-server` preset) |
| `npm run preview` | Serve the production build locally |
| `npm run generate` | Static generation (not used by the deployment) |
| `npm run typecheck` | `nuxi typecheck` (vue-tsc, strict, project references) — must report 0 errors |
| `node .output/server/index.mjs` | Run the production server (`PORT`, `HOST` env; this is what Docker/supervisord run) |

The backend is expected on `http://127.0.0.1:8000` during development:
`cd ../backend && uvicorn app.main:app --reload --port 8000`.

> `npm install` with npm 10.9.x (bundled with Node 22/23) can crash with
> `Cannot read properties of null (reading 'edgesOut')` while resolving nuxt's peer
> dependencies — an npm bug in the 10.9 line. `npm ci` from the committed
> `package-lock.json` is unaffected (that is what the Dockerfile uses). To re-resolve the
> lockfile use npm 11: `npx -y npm@11 install`.

## Runtime config

Defined in `nuxt.config.ts` → `runtimeConfig`. Every value can be overridden at runtime
(no rebuild) with an environment variable. Only `NUXT_PUBLIC_*` values reach the browser.

| Key | Env override | Default | Scope | Purpose |
|-----|--------------|---------|-------|---------|
| `apiProxyTarget` | `NUXT_API_PROXY_TARGET` | `http://127.0.0.1:8000` | server only | Where `server/api/[...].ts` forwards `/api/*` |
| `public.apiBase` | `NUXT_PUBLIC_API_BASE` | `/api` | browser + server | Base URL used by the `$api` plugin |
| `public.appName` | `NUXT_PUBLIC_APP_NAME` | `Menu Hero` | browser + server | Display name in the header / landing page |

Examples: docker-compose sets `NUXT_API_PROXY_TARGET=http://backend:8000`; the production
image's supervisord sets `NUXT_API_PROXY_TARGET=http://127.0.0.1:8000`, `PORT=3000`,
`HOST=127.0.0.1`.

## How `/api` is proxied

```
browser ──(same-origin /api/*)──▶ Nuxt/Nitro  server/api/[...].ts ──proxyRequest──▶ FastAPI
                                   (dev, docker-compose, SSR fetches)

browser ──(same-origin /api/*)──▶ nginx :8080 ── /api/ ──▶ FastAPI :8000      (production image)
                                             └── /     ──▶ Nuxt   :3000
```

- `server/api/[...].ts` is a Nitro catch-all: `proxyRequest(event, apiProxyTarget + event.path)`.
  It forwards the method, headers, body and query string and streams the upstream
  status/headers/body back untouched, so FastAPI's `404/422/500/504 {"detail": ...}` bodies
  reach the client unchanged. If the backend is down it answers `502 Bad Gateway`.
- `plugins/api.ts` provides `$api = $fetch.create({ baseURL: public.apiBase })`; every failed
  response becomes an `ApiError` (`utils/api-error.ts`) with `status` and FastAPI's `detail`.
- `composables/useApi.ts` exposes the typed endpoints `health()`, `listAgents()`, `runAgent(body)`.
- Nothing in the code base hardcodes the backend address except the `apiProxyTarget` default.

## Structure (flat Nuxt 4 layout — no `app/` directory)

```
frontend/
├── app.vue                 <NuxtLayout><NuxtPage /></NuxtLayout>
├── nuxt.config.ts          compatibilityDate, ssr, css, app.head, runtimeConfig, typescript
├── tsconfig.json           project references to the generated .nuxt/tsconfig.*.json
├── components.json         shadcn-vue CLI config (flat aliases, assets/css/tailwind.css)
├── assets/css/tailwind.css shadcn theme: Tailwind v4 import, @theme tokens, light/.dark
├── assets/css/main.css     the agent demo's own tokens and primitives, scoped to .mh-legacy
├── components/
│   ├── ui/                 shadcn-vue components (CLI-generated; edit in place, they are yours)
│   ├── AgentChat.vue       "AI Agent" card: agent <select>, message list, error bar, input
│   ├── ChatMessage.vue     one transcript entry ("User:" / "Agent:", Processing..., error)
│   └── ChatInput.vue       textarea + [→]; Enter sends, Shift+Enter newline; exposes focus()
├── composables/
│   ├── useApi.ts           health(), listAgents(), runAgent(body) via $api
│   └── useAgent.ts         useState: messages, isRunning, error, selectedAgent; runAgent(), reset()
├── layouts/
│   ├── default.vue         header (brand, Home / Agent nav), <main>, footer; carries .mh-legacy
│   └── auth.vue            passthrough for the sign-in screens (the page owns its canvas)
├── lib/utils.ts            `cn()` — the class merger every shadcn component uses
├── pages/
│   ├── index.vue           landing: description, link to /agent, client-side backend status pill
│   ├── agent.vue           renders <AgentChat />
│   └── login.vue           sign-in: wordmark, Continue with Google, backend ?error= codes
├── plugins/api.ts          $api ($fetch instance, ApiError normalisation)
├── plugins/fontawesome.ts  registers <FontAwesomeIcon> with only the icons in use
├── public/                 robots.txt, brand assets and the generated PWA icons
├── server/api/[...].ts     /api/* → apiProxyTarget proxy
├── types/api.ts            HealthResponse, AgentRequest/Response, AgentInfo, AgentListResponse, AgentEvent union
├── types/chat.ts           ChatMessage
└── utils/api-error.ts      ApiError, toApiError(), describeErrorBody()
```

Nuxt 4 uses the project root as `srcDir` when `app/` does not exist, so pages, components,
composables, layouts, plugins and utils are auto-discovered from the root. **Never create
`frontend/app/`** — `srcDir` would flip to it and every directory above would be orphaned,
which renders a blank site with no error. The shadcn-vue docs use `app/`-prefixed paths for
exactly this reason; the paths here are the flat equivalents.

## UI stack

| Piece | What it is |
|-------|------------|
| [shadcn-vue](https://www.shadcn-vue.com) + Reka UI | Components are generated into `components/ui/` by the CLI and owned by this repo — edit them, they are not a dependency to upgrade around. Auto-imported (`<Button>`, `<Alert>`) via the `shadcn` block in `nuxt.config.ts` |
| Tailwind CSS v4 | Via `@tailwindcss/vite`. Theme tokens live in `assets/css/tailwind.css` |
| `@nuxtjs/color-mode` | Writes `class="dark"` on `<html>` (`classSuffix: ''`), which is what shadcn's `dark` variant matches |
| Font Awesome | `plugins/fontawesome.ts` registers `<FontAwesomeIcon>` and adds **only the icons used** — importing a whole pack ships thousands of unused paths. `config.autoAddCss = false` plus the core stylesheet in `nuxt.config.ts` `css` keeps icons from flashing at the wrong size on hydration |
| `components/GoogleMark.vue` | Google's official four-colour G, inline. FA's brand set is single-colour, so `fa-google` renders a flat monochrome mark — and Google asks that its logo appear in its own colours. One glyph does not justify a second icon library, so this is the only inline exception |
| Geist | Self-hosted through `@fontsource-variable/geist`, not the CLI's Google Fonts URL: an offline-capable PWA should not block first paint on a third-party host |

Add a component with the CLI:

```bash
npx shadcn-vue@latest add dialog
```

If the CLI dies with `Cannot find module 'components'`, its config loader is resolving the
`components/` **directory** instead of `components.json`. Move the directory aside for the
duration of the command and put it back afterwards.

Two stylesheets coexist. `assets/css/tailwind.css` owns the shadcn theme; `assets/css/main.css`
is the older hand-written system behind the agent demo. Keeping them apart takes two rules:

- Tokens the two both want (`--color-accent`, `--color-border`, `--font-sans`,
  `--radius-sm|md|lg`) carry an `--mh-` prefix on the legacy side.
- Every legacy rule with a bare element selector is scoped as `:where(.mh-legacy) …`,
  the class `layouts/default.vue` puts on its root. `:where()` because it must add **no**
  specificity: a plain `.mh-legacy a` outranks `.btn--primary` and paints that button's
  label the same orange as its background. Unlayered element selectors also beat
  Tailwind's `@layer base` regardless of load order, which is why the scoping is needed at
  all.

New UI should use shadcn components; `main.css` is for the demo pages until they are
migrated.

`pages/login.vue` pins `class="dark"` on its root rather than following `@nuxtjs/color-mode`:
a full-bleed sign-in screen reads as one deliberate surface, and pinning it means every
shadcn component on the page resolves its dark tokens instead of the viewer's theme. The
rest of the app still follows the system setting. Remove that one class to make it
theme-aware.

## PWA

`@vite-pwa/nuxt` generates `manifest.webmanifest` and `sw.js` at build time; `<VitePwaManifest />`
in `app.vue` is what links them into the page (without it both files exist and nothing
references them, so the browser never offers to install the app). Icons come from
`public/logo.svg` via `@vite-pwa/assets-generator`:

```bash
npx @vite-pwa/assets-generator --preset minimal-2023 public/logo.svg
```

### Brand assets

`public/` carries the real MenuHero marks, copied from the marketing repo — do not
substitute anything else:

| File | What it is | Used by |
|------|-----------|---------|
| `logo.svg` | The app icon: navy `#172033` rounded square, three orange `#F7941D` bars | the favicon and the source the PWA icons are generated from |
| `brand-mark.png` | The shield logo | the wordmark on `/login` and in the demo header, on a white tile (its navy would vanish on a dark background) |
| `pwa-*.png`, `maskable-icon-*.png`, `apple-touch-icon-*.png`, `favicon.ico` | Generated | the manifest and iOS |

Regenerate the icon set after changing `logo.svg`:

```bash
npx @vite-pwa/assets-generator --preset minimal-2023 public/logo.svg
```

The wordmark is **MenuHero**, one word, as on the marketing site. The backend's
`project_name` and the repo docs still say "Menu Hero"; only the user-facing frontend
strings were aligned.

### Service worker

`workbox.navigateFallbackDenylist: [/^\/api\//]` is load-bearing: `GET /api/v1/auth/google`
and its callback are top-level navigations, and without the denylist the service worker
answers them with the SPA shell. Google sign-in would then fail **in production only** —
where the worker is registered — and look like a redirect loop rather than a caching bug.

The worker also runs in dev (`devOptions.enabled: true`). It has to: **a manifest alone
does not make a site installable** — Chrome wants a registered service worker with a fetch
handler as well, so with the worker off in dev the browser never offers to install the app
and the PWA looks broken. The dev worker leaves `navigateFallbackAllowlist` at its default
`[/^\/$/]`, so it only falls back for `/` and cannot swallow an `/api/*` navigation.

To confirm it is installable: DevTools → **Application → Manifest**, which lists any
installability error, or look for the install icon at the right of Chrome's address bar
(also under ⋮ → *Cast, save and share*). On iOS it is Share → *Add to Home Screen*, which
uses the `apple-touch-icon`, not the manifest.

Verified on a real build as well:

```bash
npm run build && npm run preview     # http://localhost:3000
```

`.nuxt/`, `.output/` and `node_modules/` are build artefacts and are git-ignored.

## Smoke test

```bash
# terminal 1 — backend (or any server answering the contract on port 8000)
cd ../backend && uvicorn app.main:app --port 8000

# terminal 2
npm run dev
curl -s http://localhost:3000/api/health                 # {"status":"ok"} via the proxy
curl -s -X POST http://localhost:3000/api/agents/run \
     -H 'content-type: application/json' -d '{"message":"hi"}'
```

Same with the production build: `npm run build && PORT=3000 node .output/server/index.mjs`.
