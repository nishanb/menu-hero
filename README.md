# Menu Hero Core

A three-layer monorepo: a Nuxt front end, a FastAPI back end, and an independent Python
agent system. It runs today as a single application on one EC2 instance behind Elastic
Beanstalk, and the agent package is deliberately free of any web-framework dependency so
the same code can later run in background workers behind a queue.

```
Nuxt (browser + SSR)  →  FastAPI  →  AgentService  →  agents/  →  ExampleAgent
        :3000              :8000       (bridge)      (package)
```

---

## Architecture

### Layers

| Layer | Stack | Location | Talks to |
|-------|-------|----------|----------|
| Frontend | Nuxt 4, Vue 3, TypeScript, shadcn-vue + Tailwind v4, PWA | `frontend/` | the backend, over same-origin `/api/*` |
| Backend | Python 3.12+, FastAPI, Pydantic v2 | `backend/` | the agent package, in process |
| Agent system | Python 3.12+, Pydantic v2 only | `agents/` | LLM providers, tools, databases |
| Workers | placeholder for the queue-based future | `workers/` | the same `agents/` package |

### Dependency direction

```
frontend  ──→  backend  ──→  agents  ──→  LLM providers / tools / stores
```

Allowed: `frontend → backend API`, `backend → agents`, `agents → external integrations`.

Never allowed, and enforced by `agents/tests/test_boundaries.py`, which walks the AST of
every module in the package:

- `agents → fastapi / starlette / uvicorn` or any backend module
- `agents → frontend`
- `frontend → agents` directly

The agent package declares exactly two runtime dependencies, `pydantic` and
`pydantic-settings`. No LLM key ever reaches the browser: only `NUXT_PUBLIC_*` values are
public, and the provider key lives in the agent package's own settings.

### Request path

```
Browser  ── POST /api/agents/run ──►  Nuxt server route  (dev / compose only)
                                          │  proxyRequest
                                          ▼
                                     FastAPI route          backend/app/api/routes/agents.py
                                          │  no agent logic here
                                          ▼
                                     AgentService           backend/app/services/agent_service.py
                                          │  AgentExecutor protocol
                                          ▼
                                InProcessAgentExecutor  ──►  agents.run_agent()
                                                                  │
                                                             AgentRegistry → ExampleAgent
                                                                  │  AgentContext → memory, tools, events
                                                                  ▼
                                                             AgentResult
```

In production nginx sends `/api/` straight to FastAPI, so the Nuxt proxy only serves
server-side rendering fetches.

### Repository layout

```
menu-hero-core/
├── frontend/                  Nuxt application (flat layout, no app/ directory)
│   ├── assets/css/            design tokens, light and dark
│   ├── components/            AgentChat, ChatMessage, ChatInput
│   ├── composables/           useApi.ts, useAgent.ts
│   ├── layouts/  pages/       default layout; index.vue, agent.vue
│   ├── plugins/api.ts         $api = $fetch instance bound to the public API base
│   ├── server/api/[...].ts    proxies /api/* to FastAPI (dev, compose, SSR)
│   ├── types/  utils/         API and chat types, ApiError
│   └── nuxt.config.ts         runtime configuration
├── backend/                   FastAPI application
│   ├── app/api/routes/        health.py, agents.py
│   ├── app/core/              config.py, logging.py, database.py
│   ├── app/dependencies/      agents.py, database.py
│   ├── app/models/            MongoDocument, MongoRepository (no collections yet)
│   ├── app/schemas/           HTTP request and response models
│   ├── app/services/          AgentService, AgentExecutor protocol
│   ├── app/main.py            application factory, lifespan, error mapping
│   └── tests/
├── agents/                    independent agent package
│   ├── core/                  agent.py, context.py, events.py, exceptions.py,
│   │                          registry.py, runner.py, config.py
│   ├── implementations/       example_agent.py
│   ├── integrations/llm.py    LLMClient interface + stub provider
│   ├── memory/                conversation memory interface + in-memory store
│   ├── schemas/               AgentRequest, AgentResult, AgentInfo, Message
│   ├── tools/                 BaseTool, ToolRegistry, example tool
│   ├── workflows/             SequentialWorkflow, example workflow
│   └── tests/
├── workers/                   placeholder; see workers/README.md
├── deploy/                    nginx.conf and supervisord.conf for the single image
├── .ebextensions/ .platform/  Elastic Beanstalk configuration
├── Dockerfile                 multi-stage; the last stage is the combined image
└── docker-compose.yml         MongoDB + backend + frontend for local work
```

---

## Local development

Requirements: Node 20.19+ (22 LTS recommended), Python 3.12+, and
[uv](https://docs.astral.sh/uv/). MongoDB is optional.

### Backend

```bash
cd backend
uv sync
uv run uvicorn app.main:app --reload --port 8000
```

### Frontend

```bash
cd frontend
npm install          # npm 11 recommended: npx -y npm@11 install
npm run dev          # http://localhost:3000
```

The browser only ever calls same-origin `/api/*`. In development the Nuxt server route
forwards those calls to `NUXT_API_PROXY_TARGET`, so there is no CORS setup and no backend
host in browser code.

The UI is [shadcn-vue](https://www.shadcn-vue.com) on Tailwind CSS v4, with Font Awesome
icons, and the app installs as a PWA (`@vite-pwa/nuxt`). `frontend/README.md` covers the
stack, how the two stylesheets are kept apart, and the service-worker rule that keeps
`/api/*` reachable. Sign-in lives at `/login`.

### Google sign-in (management app)

Create an **OAuth 2.0 Web application** client at
[console.cloud.google.com/apis/credentials](https://console.cloud.google.com/apis/credentials),
add `http://localhost:3000/api/v1/auth/google/callback` as an authorised redirect URI, and
put the id and secret in `.env`. Then `http://localhost:3000/api/v1/auth/google` starts the
flow. Until they are set, that endpoint answers 503. The returned `id_token` has its
signature verified against Google's JWKS (joserfc); the authorization URL is built by
authlib.

The callback is registered on the **frontend** origin, not the backend's: Nuxt proxies
`/api/*` to FastAPI, so the session cookie is set on the host the app is served from.
Cookies are scoped by host and ignore the port, so mixing `localhost` and `127.0.0.1`
between `GOOGLE_REDIRECT_URI`, `FRONTEND_BASE_URL` and the browser silently breaks sign-in
— the backend warns at start-up when the two disagree. See `backend/README.md` for the
endpoints, the four roles and the invite flow.

### Restaurant onboarding

A person who signs in and belongs to no restaurant is offered `/onboarding`, its own
section of the app rather than a dialog: the form is long, the Google import is a round
trip out and back, and a page can be linked to and reloaded without losing the thread. The
dashboard offers it; nothing forces it, because an invited server also arrives belonging to
nothing and must not be pushed into creating a restaurant.

Whoever creates a restaurant owns it. This is a **deliberate departure from HLD 3.1**,
which says tenants are operator-created with no self-serve signup — onboarding cannot work
otherwise. What survives of the operator rule is that only a platform admin may create a
restaurant *for someone else* (`owner_email`); it is ignored for everyone else. The slug is
derived from the name server-side with numbered suffixes on collision, so two restaurants
may share a name.

The restaurant a person is working on is remembered on the server (`users.last_tenant_id`),
so it survives a reload and follows them to another device. It is a preference and never a
grant: every read re-checks it against the memberships, so a revoked membership silently
stops it being the active one. There is deliberately no `restaurants_managed` array on the
user — `memberships` already is that list, with the role attached.

Invitations live in **Settings → Team**, next to the people they concern. Nothing is
emailed yet, so creating one returns a link shown exactly once (only a digest is stored);
`/invite?token=…` is where it lands.

### The floor plan and its tables

**Settings → Floor Plan** shows the room as it is — read-only, with the tables named on
it. The plan itself has no name: there is one per restaurant, so it has nothing to be told
apart from. Editing is a deliberate act behind an **Edit floor plan** dialog, because arranging a
floor is a task with a beginning and an end rather than a setting to be nudged: it wants
width, a scratch buffer and an explicit Save. One plan per restaurant, so there is nothing
to choose between.

In the dialog, tables come in four shapes (round, square, diamond, long), are dragged and
resized on a grid, and carry a name and a seat count. Walls and captions can be dropped
alongside them so the room is recognisable. The page behind keeps showing the *saved* plan
throughout, and closing the dialog keeps unsaved work rather than discarding it — only Save
and Discard decide anything.

The data model splits the two halves on purpose, and the split is what makes the editor
safe to redraw:

* **`floor_plans`** is the drawing — one document per tenant, replaced whole on every save.
  The editor is a buffer with Save and Discard, so a partial update would describe half a
  room.
* **`tables`** is identity. An order points at a table (`orders.table_id`) and a QR code
  encodes one, so a table's `_id` has to outlive any number of redraws. Saving reconciles
  the collection: a renamed table keeps its id, a table taken off the plan is *deactivated*
  rather than deleted, and one put back under the same name comes home to the same row —
  which is what stops a rearranged room from invalidating QR codes already printed.

Owners arrange the floor; staff get the same view without a way in, because a server needs
to know which table is which but not to move it. QR generation and table tokens (HLD `POST /tables/{id}/token`) are not built yet —
this is the data they will be built on.

### Menus

**Menus** in the rail is a section rather than a page: Menu, Categories, Menu on/off, Import
menu, Physical menu and QR code. It stays folded until it is clicked — the route never opens
it — and only Categories is built so far; the rest are pages that say where they are up to,
which beats a link that 404s.

**Menus → Categories** is the sections a menu is read in. Each has a name (unique per
restaurant, case-insensitively — two headings called Starters is a mistake every time), a
`rank` that decides the running order, and a status of `active` or `hidden`. Owners edit;
staff read, because a server needs to know how the menu is organised.

Re-ordering renumbers the whole list densely rather than nudging one rank. Nudging looks
cheaper and is quietly broken: ranks may tie, ties fall back to the name, so "move up" would
work for Mains above Starters and do visibly nothing for Zuppa above Starters.

### Menu management

**Menus → Menu** is the two-pane workspace a POS uses and the people filling it in already
know: the sections down the left with their counts, the dishes on the right. A section is
always selected — there is no "everything" row — and the rail sticks to the viewport and
scrolls inside itself, because a menu with 35 sections is taller than the screen and a rail
that scrolls away means scrolling back up to change section.

Search is the exception to the section filter: typing looks across the **whole** menu, by
name, online name or short code, since with no "everything" row that is the only way to find
a dish whose section you have forgotten. The stripe down each row is the dietary attribute,
which is how a server reads a menu at a glance; a dish that is off today's menu is dimmed,
but switching it is Menu on/off's job, not this table's.

Each dish opens the same configuration form a POS shows — category, name, online display
name, short codes, base price, container charges, weight/portion, profit margin, dietary,
order types, GST type, where it is exposed, decimal quantities, manufacturing and expiry
dates, HSN code and description. The closed sets (order types, exposures, units, GST) come
from `GET /menu/options`, which serves the very lists the document model validates against —
hard-coding them in the UI is how a form and its validators drift apart.

A picture is uploaded from the form and stored through the same `ImageStore` the import uses,
so the item ends up holding a URL and never the bytes. It is a separate call rather than
base64 in the item body: a 2 MB image inside a JSON patch is 2 MB re-sent every time somebody
changes the price.

Dietary is deliberately not the same as the POS's — single-select even though a POS draws
checkboxes, because a dish is not both veg and non-veg and an export carries one value per
item.

### Table QR codes

**Menus → Table QR code** turns the tables on the floor plan into codes you can laminate, in
five designs. **Showcase** is the flagship and the default: a full card on a colour ground
with the restaurant's name, a large SCAN ME, the code on a white panel inside accent corner
brackets, the table in a pill, and a three-step strip along the foot — the standing sign that
gets read from across the room, one, two or three to a page. It takes one of five curated
grounds (Ink, Forest, Terracotta, Wine, Slate) and an optional line above the call to action.
Curated pairs rather than a colour picker, because a picker produces combinations nobody
would choose on purpose and these have to survive being printed flat on card.

The other four are for when a sticker is all that is wanted: **Card** (rounded, with a header
bar), **Table tent** (two halves, one inverted, so a fold reads from both sides), **Badge** (a
circular sticker) and **Plain** (code and label, cheapest to print and easiest to cut) — at
32, 48 or 72 mm, several to an A4 sheet. A code for the door is included by default: somebody reading the
menu at the counter has not sat down anywhere, and handing them table A1's code would seat
them at it.

**The code encodes the table, not a session.** A printed sticker outlives any number of
seatings, so it points at a stable table URL and the server mints the short-lived table token
when a diner actually scans it (HLD 3.4). That is the whole reason a table is an identity
that survives the floor plan being redrawn — putting a token on the sticker would mean
reprinting every code every service.

Codes are rendered as **SVG**, not canvas. A canvas QR is a bitmap: enlarge it for a 72 mm
tent card and the modules go soft, and a 600 dpi printer has nothing extra to work with.

The diner page is not live yet, so the codes are for laminating now and scanning once it is.

### The physical menu

**Menus → Physical menu** turns the live menu into something you can put on a table, in four
templates. Two are *designed* — a menu that goes on a table is part of the room, and a plain
list of names and prices is a missed opportunity:

* **Elegant** — cream ground, Playfair Display over a serif body, letter-spaced small caps,
  a diamond rule. Reads like a restaurant.
* **Signature** — a dark masthead that bleeds to the paper edge, ruled section headings,
  italic descriptions, a boxed dietary legend and a dark footer band.

Two are utilities and look like it on purpose, because the till and the kitchen wall want
density and nothing else: **Compact** (three dense columns) and **Counter sheet** (a plain
table).

All four take A4 or Letter, with a **cover page**, **descriptions** and **veg marks** each
optional. The cover carries the logo, the name, the description, the services and — because
in India an FSSAI number is expected on a printed menu — whatever the restaurant keeps in its
"Additional information". The legend only explains the marks that actually appear on the
menu in hand.

Only dishes that are **on** the menu are printed. A paper menu listing something the kitchen
ran out of is the exact failure this feature exists to avoid, so Menu on/off decides what
appears here.

The display face is self-hosted (`@fontsource/playfair-display`) and imported inside
`PhysicalMenu.vue` rather than in `nuxt.config`, so it is code-split with the component and
no other page pays for a font only the printed menu uses.

It prints through the browser rather than a PDF library, and that is a considered choice.
`window.print()` with "Save as PDF" as the destination produces a real PDF — vector text, the
actual fonts, page breaks the engine worked out from the content. The alternatives are worse
in ways that show on paper: `jsPDF` + `html2canvas` rasterises, so a menu printed at 300 dpi
looks like a screenshot; a server-side renderer (WeasyPrint, headless Chromium) means system
libraries or a browser in the container for output no better than this. The cost is one extra
click in the print dialog.

Two print details worth knowing. The CSS in `PhysicalMenu.vue` is deliberately **not scoped**
— it has to reach `body *`, and it hides by `visibility` rather than `display` because the
sheet lives inside the sidebar layout, so hiding its ancestors would hide it too. And `@page`
carries both the paper size and the margin, written into a style tag because `@page` cannot
read a CSS variable: the designed templates print at `margin: 0` and lay out their own, which
is what lets the Signature masthead bleed.

### Menu on/off

**Menus → Menu on/off** is what is being served *right now*. Every section on one page with
its dishes and a switch each, because taking things off is something a floor manager does in
a burst at the start of service — three dishes here, a whole section there — and paging
between categories to do it would be the wrong shape. The rail jumps to a section rather than
filtering to it; checkboxes and per-section **All on / All off** cover the bulk cases.

A section switch is **one request**, not one per dish: `POST /menu/availability` takes either
a list of ids or a category name, and a real section runs to 28 items. Passing the category
rather than the ids it happened to hold also keeps it right if somebody adds a dish while the
page is open.

Nothing here publishes anything. Availability is a *service* decision — it changes what a
diner is offered tonight and never writes a new version of the menu — which is why it has its
own page, its own endpoint, and never says "save".

### The POS

**POS** in the rail is the till, and it takes the whole screen: its own layout (`layouts/pos.vue`)
with no sidebar, no page margins and no page-level scrolling, because a terminal is a screen
that is on all shift, tapped at arm's length between carrying plates. One slim bar — where
you are, the time, a way out — and everything else is the work.

The front door is one screen with three sections, each taking all of it. **KOTs** first: the
kitchen's queue — tickets nobody has seen yet, oldest on top — and the two things a kitchen
does to a ticket: **Acknowledge**, which takes it off the queue on every till (set once,
never cleared; the order's own history keeps it), and **Print**. A ticket says who
sent it (a captain at the till today; the table itself through the QR menu once that flow
is live — the `source` field is already there) and the tab wears a count of the unseen
ones from the other views. Then the room: **Floor plan**, the saved plan **scaled to fit
the box it is given and never scrolled** (a table that is off-screen is a table nobody
seats), every table painted by state — free, seated, billed — and **Tables**, the same
tables as a list. A tap on a table seats it or opens what it is running up; **New bill**
starts a takeaway, which has no table and sits in a strip under whichever room view is
showing. The floor polls every five seconds, so two tills see each other's tables change.

What the till runs is a setting — **Settings → POS**. *Billing* is the till proper: the
floor plan and its tables, takeaway bills, sending rounds, settling. Switched off, the POS
is the kitchen display — the KOT board and nothing else, no **New bill**, no running bills —
and the backend refuses to open any order (409), table or takeaway. Kitchen tickets have no
switch: an order is a ticket wherever it comes from, and a kitchen that cannot see its
tickets is not a configuration, it is an outage. Acknowledging a ticket turns the button to
**Acked**; the tile leaves the queue at the next poll.

The order screen is the shape of every till: the menu filling the left — sections as a rail
of big buttons to slide through (no "All"; the first section is where it opens), the dishes
as tiles washed by diet, search over them for a server who types "ND" rather than scrolling
to Neer Dosa — and the ticket down the right. Dishes tapped land on the ticket *pending*; a
second tap on the same dish is one more of it, not a second line; quantity, a note for the
kitchen and removal are all allowed while the line is pending.

The buttons under the ticket are the whole lifecycle. **Send** turns the pending lines into a
KOT — a numbered ticket for the kitchen, printed on 80 mm paper the moment it is created —
and from then on those lines are fixed: what the kitchen has been told is not edited behind
its back. A table can go through as many rounds as it likes; each is its own ticket. **Bill**
*settles*: it refuses while anything is pending (send it or remove it — a bill that ignores a
round is wrong), prints the receipt, closes the order and frees the table in one tap, because
at the counter "bill" and "paid" are one moment and a table stuck in "billed" until somebody
remembers a second button is a table nobody can seat. The backend keeps `bill` and `close`
apart, so a close that fails after the bill leaves the order `billed` with **Paid** and
**Reprint** on offer rather than lost. **Cancel** asks first and says how many tickets are
already in the kitchen, because the software cannot un-cook them. There is no tax line yet:
the receipt's total is its subtotal until the restaurant carries a GST rate, and `OrderOut`
says so.

Printing is one pipeline for every screen (`composables/usePosPrinter.ts`, rendered by
`<PosPrintSheets>`): the ticket or the bill goes into a hidden print area, the page prints,
`afterprint` clears it.

Two things make it safe to run from several devices at once. Seating is **idempotent per
table** — a partial unique index on `{tenant_id, table_id}` for open orders means two taps
on A1 return the same order rather than two — and a takeaway carries an `idempotency_key`
minted by the client, so a retried request cannot open a second bill. Numbers come from a
`sequences` document per tenant (`$inc` on upsert), one series for orders and one for
tickets, so they are gap-free and human. Prices and names are **snapshotted onto the line**
at the moment it is added: a menu edit tonight does not change what table B2 was charged for
lunch.

### Ordering from the table

`/restaurant/<restaurant-id>/order?table=<table-id>` is the page behind the QR code on the
table — and the one place in the app with **no sign-in and no desktop**. A person at A3 has
a phone and a code and nothing else; asking them to sign in to see what is for dinner is how
a restaurant loses the order. The page is its own layout (`layouts/diner.vue`): one phone
column, safe-area aware, nothing of the management app in it.

It opens on a **welcome** — the restaurant's name over a plate spinning up while the menu
arrives, then one choice: **Chat & order** or **Browse the menu** (once per visit; session
storage). Both are always a tap away after that, as floating buttons at the thumb.

The menu is **as the table should see it**: available dishes only, in the restaurant's
section order, hidden sections hidden, and the projection deliberately narrow — name,
description, diet mark, price, picture, forms — no short codes, costs, margins or stock
dates (`schemas/public.py`). A dish with no photo gets a drawn stand-in tinted by diet, so
the list keeps one rhythm. The sticky top is one row — search and a **Filters** button —
and the filters (veg / non-veg / egg, under ₹200, sort by price) live in a sheet, with what
is chosen shown as removable chips only while something is; **Menu**, floating, opens the
table of contents with counts and jumps. An **Add** rides the bottom edge of every dish's
photo and turns into a stepper once the dish is in the round; a dish with forms asks "How
should it come?" in a sheet from the bottom, because the thumb is at the bottom. The round
lives in `localStorage` per restaurant and table, so a locked phone comes back to it.

**Chat & order** is the ordering agent's seat at the table (HLD 3.6). Until the agent is
wired in, the seat is taken by `composables/useMenuAssistant.ts`: a search over the loaded
menu that talks — it reads the diet and the budget out of the question ("chicken under
250"), matches the rest against names, sections and descriptions, and answers with dishes
that can be added from the thread. Same shape in, same shape out, so the chat does not
change when the agent arrives.

**Place order** goes straight to the kitchen. `POST /public/restaurants/{id}/orders` seats
the table if it is not seated (the same idempotent open a captain gets), adds the lines at
today's prices, and sends the round as a KOT with `source=diner` and `sent_by_name="Table
A1"` — one call doing what a captain does in three, because there is no captain to press
Send. The ticket lands on the POS's KOTs board as **From the table · QR** and the order on
the floor exactly as a captain's would; the diner is told the order and ticket numbers and
that the bill is settled at the counter. A second round goes on the same order. A table that
is already billed is refused ("ask your server"); a dish that is off the menu is refused;
the POS **Billing** switch does not apply here — a restaurant with the till off is exactly
one that takes its orders this way.

Menu pictures (`/v1/images/{id}`) are public for the same reason: the diner's menu shows
them to whoever scanned the code, and a photo of a dosa is the least secret thing a
restaurant owns.

Without a `table` the page still shows the menu (it is the door's code too) but does not
offer to order — there is nowhere to send it. **Settings → POS → Order from the table**
lists every link, one per table plus the door, with **Open** and **Copy**, so it can be tried
on a phone before the codes are printed; **Menus → Table QR code** encodes the same links.

### Importing a menu from a POS export

**Menus → Import menu** takes the item export a POS writes and turns it into the menu. It is
two calls of one endpoint, and the first is the point: choosing a file only *reads* it —
`dry_run=true` reports how many items were found, which sections are new, and every row it
could not make sense of, and writes nothing. Committing is a second, deliberate click. HLD
9.1 puts a person between an import and a live menu; a preview that costs one upload is the
cheapest way to keep them there.

Committing **replaces** the item list. An export is somebody saying "this is my menu", not a
patch to merge, so the confirmation says how many items are about to go. Categories named in
the file are *added* if the restaurant lacks them, in the order the file introduces them —
existing ones keep their rank and their hidden/active status, because those are the owner's
decisions and an import has no business overruling them.

**Pictures.** An optional image column (`Image`, `Item_Image`, `Image_Base64`, `Photo` or
`Image_URL` — the first one present wins) is read alongside the rest. A cell may hold an
`https://` link, which is left alone because it is already on somebody's CDN, or a whole
image inline as `data:image/png;base64,…`.

Inline images are decoded **once, on commit**, and stored as bytes — never kept as a data URL
on four hundred documents. What lands on the item is `image_url` and nothing else, which is
the point: `services/image_store.py` is a one-method protocol, and pointing it at a real CDN
is a new implementation and a dependency swap, with no stored document changing. Until then
`DatabaseImageStore` keeps the bytes in `menu_images`, content-addressed — a POS export
repeats one placeholder across dozens of rows, and in testing 136 rows sharing a picture
stored exactly one copy. SVG is refused: it is a document that can carry script, not a
picture.

The format is the one Petpooja and its lookalikes export, and `services/menu_import.py`
survives three specific awkwardnesses it has, each of which is a real bug if ignored:

* **the header repeats itself** — `Variation`, `Variation_Price`, `Variation_Sap_Code` and
  `Variation_Packing_Charges` appear three times over, so a `DictReader` keeps only the last
  of each and loses two variations in three. It reads by position instead;
* **rows are ragged** — 21, 30 or 34 fields depending on how many variations a dish has, so
  indexing past the end is the normal case, not an error;
* **a dish priced by its variations carries `Price` 0** — reading that as the price puts a
  menu full of free food on the table.

Nothing in a row is fatal. One unreadable price out of four hundred costs that cell and says
so in the warnings, rather than losing the import.

### Importing from Google Business Profile

An owner can connect the Google account that manages their business and import a location
as a restaurant — name, description, address, phone, website and map link.

There is no feature switch: the import is offered wherever it can work, which means the
same OAuth client sign-in already uses plus a `SECRET_KEY`. The key is not optional — the
refresh token is encrypted at rest with one derived from it — so a deployment without one
says the import is unavailable rather than offering a button it cannot honour.

This is a **second OAuth grant**, separate from sign-in: scope
`https://www.googleapis.com/auth/business.manage`, `access_type=offline`, its own redirect
URI and state cookie. Sign-in deliberately keeps `openid email profile` and stores no
credential — widening it would put everyone through a business-management consent screen
and store a real credential for people who never asked to import anything. The refresh
token is encrypted at rest with a key derived from `SECRET_KEY`
(`backend/app/core/crypto.py`) and is never returned by any endpoint.

Whether Google will actually *answer* is a separate question, and not one the app can
settle up front. In the **same Google Cloud project** as the sign-in client:

1. request access at
   [developers.google.com/my-business/content/prereqs](https://developers.google.com/my-business/content/prereqs)
   — the Business Profile APIs are allow-listed per project and answer `PERMISSION_DENIED`
   until the request is approved;
2. enable the *My Business Account Management API* and the *My Business Business
   Information API*;
3. register `GOOGLE_BUSINESS_REDIRECT_URI` as an authorised redirect URI.

Until the project is approved, connecting succeeds and the first listing fails with
`PERMISSION_DENIED`, which is shown to the owner with that explanation attached rather than
as a generic error. Onboarding never depends on it: the manual form is always there.

### Agent package, without FastAPI

```bash
cd agents
uv sync
uv run python -m agents "hello"            # prints the AgentResult as JSON
uv run python -m agents "hello" --stream   # prints one JSON line per event
```

### Tests

```bash
cd agents   && uv run pytest        # 82 tests, no FastAPI involved
cd backend  && uv run pytest        # 157 tests (44 need a live MongoDB, else skipped)
cd frontend && npm run typecheck && npm run build
```

To include the MongoDB repository tests:

```bash
docker run --rm -d -p 27017:27017 --name mh-mongo mongo:8
cd backend && TEST_MONGODB_URL=mongodb://127.0.0.1:27017 uv run pytest
docker rm -f mh-mongo
```

Nothing in the suite touches the network: Google is replaced by a test double that still
runs the real `id_token` claim validation, and `tests/test_google_oauth.py` serves a fake
Google over an `httpx.MockTransport` with genuinely signed tokens.

Linting and typing, in `agents/` and `backend/`:

```bash
uv run ruff format . && uv run ruff check . && uv run mypy .
```

### Everything in Docker

```bash
docker compose up --build     # MongoDB :27017, FastAPI :8000, Nuxt :3000
docker compose down -v        # also drops the mongodata volume
```

This builds the *runtime* images: the front end is a compiled Nitro bundle and the back end
a locked venv, so a source edit needs a rebuild. For day-to-day work use the dev overlay
instead.

### Docker, with live reload

```bash
cp .env.example .env          # required: the overlay bind-mounts this file
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

Shorter, for a shell session:

```bash
export COMPOSE_FILE=docker-compose.yml:docker-compose.dev.yml
docker compose up --build     # and then plain `docker compose logs -f`, `down`, ...
```

`docker-compose.dev.yml` switches both services to the `backend-dev` / `frontend-dev`
stages, bind-mounts `backend/`, `agents/` and `frontend/`, and lets each process watch its
own source: **uvicorn `--reload`** (watching `/app/backend/app` *and* `/app/agents`) and
**Vite HMR**. Edit a file on the host and the container picks it up — no rebuild. Rebuild
only when a dependency changes:

```bash
docker compose build backend                          # after uv.lock / pyproject.toml
docker volume rm menu-hero-core_frontend_node_modules \
  && docker compose build frontend                    # after package-lock.json
```

The extra step for the front end is not optional: `node_modules` is a named volume, and
Docker seeds it from the image **only when it is empty**, so a rebuilt image is shadowed by
the packages the volume already holds. `docker compose down -v` does the same thing more
bluntly.

Two details that make it work, and that are easy to get wrong when copying this pattern:

- The container venv is at `/opt/venv` and `node_modules` is a **named volume**, so the
  host's macOS-built `backend/.venv` and `frontend/node_modules` cannot shadow the Linux
  ones the images installed.
- `WATCHFILES_FORCE_POLLING=true` is set for the backend because Docker Desktop does not
  forward inotify events reliably from a bind mount; drop it on Linux, where it is pure
  overhead.

Running the tests inside the stack:

```bash
docker compose exec -e TEST_MONGODB_URL=mongodb://mongo:27017 backend pytest -q
docker compose exec backend ruff check .
```

---

## Configuration

Copy `.env.example` to `.env` at the repository root. It is git-ignored, and both Python
packages read it; real environment variables always win.

| Variable | Read by | Default | Reaches the browser |
|----------|---------|---------|---------------------|
| `APP_ENV` | backend | `development` | no |
| `SECRET_KEY` | backend | empty; **required** when `APP_ENV=production` | no |
| `DATABASE_URL` | backend | unset | no |
| `MONGODB_DATABASE` | backend | `menuhero` | no |
| `CORS_ORIGINS` | backend | `http://localhost:3000` | no |
| `LOG_LEVEL` | backend | `INFO` | no |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | backend | empty; sign-in answers 503 until set | no |
| `GOOGLE_REDIRECT_URI` | backend | `http://localhost:3000/api/v1/auth/google/callback` | no |
| `FRONTEND_BASE_URL` | backend | `http://localhost:3000` | no |
| `SESSION_TTL_DAYS` | backend | `30` | no |
| `INVITE_TTL_DAYS` | backend | `14` | no |
| `BOOTSTRAP_ADMIN_EMAILS` | backend | empty | no |
| `GOOGLE_BUSINESS_REDIRECT_URI` | backend | `http://localhost:3000/api/v1/google-business/callback` | no |
| `LLM_API_KEY` | agents | unset | **never** |
| `LLM_PROVIDER` | agents | `stub` | no |
| `LLM_MODEL` | agents | unset | no |
| `AGENT_TIMEOUT_SECONDS` | agents | `60` | no |
| `NUXT_API_PROXY_TARGET` | Nuxt server | `http://127.0.0.1:8000` | no, server only |
| `NUXT_PUBLIC_API_BASE` | Nuxt | `/api` | yes |
| `NUXT_PUBLIC_APP_NAME` | Nuxt | `Menu Hero` | yes |

### Database

`DATABASE_URL` holds a MongoDB connection string, `mongodb://…` or `mongodb+srv://…`, and
is optional: the application starts and serves the agent demo without it, and routes that
ask for a database answer 503 while it is unset. Nothing connects at import or start-up.
The database name comes from the path of the URL when it has one, and from
`MONGODB_DATABASE` otherwise.

The connection string is validated as a string rather than parsed into a pydantic
`MongoDsn`, because pydantic normalises a URL by adding the default port and PyMongo
rejects any `mongodb+srv://` URI that carries one, which would break every Atlas
deployment.

Database access stays in `backend/app/models/` (documents and repositories) and
`backend/app/services/`. The agent package never imports the driver; if agents need
persistence later they get a service interface, not a document class.

---

## API

All endpoints are mounted under `/api`.

| Method | Path | Body | Response |
|--------|------|------|----------|
| GET | `/api/health` | — | `{"status": "ok"}` |
| GET | `/api/agents` | — | `{"agents": [{"name", "description"}]}` |
| POST | `/api/agents/run` | `{"message": "Hello agent", "agent": "example"}` | `{"response": "Processed: Hello agent", "agent": "example", "metadata": {…}}` |
| POST | `/api/agents/stream` | same as run | `text/event-stream` of agent events |

The management surface is versioned under `/api/v1`:

| Method | Path | Who | Purpose |
|--------|------|-----|---------|
| GET | `/v1/auth/google`, `/v1/auth/google/callback` | anyone | Google sign-in round trip |
| GET | `/v1/auth/me` | signed in | the person, their roles, and which restaurant to open on |
| POST | `/v1/auth/logout`, `/v1/auth/invites/accept` | signed in | sign out; accept an invite by token |
| POST | `/v1/tenants` | signed in | create a restaurant (the caller owns it) |
| GET | `/v1/tenants` | signed in | the caller's restaurants, without logos, plus `active_tenant_id` |
| GET | `/v1/tenants/options` | signed in | suggested services and diet options |
| GET/PATCH | `/v1/tenants/{id}` | member / owner | one restaurant with its logo; edit its profile, including `pos` (`billing` on/off) |
| PUT | `/v1/tenants/{id}/current` | member | remember this restaurant across devices |
| GET/PUT | `/v1/tenants/{id}/floor-plan` | member / owner | the floor plan and its tables; saving reconciles the tables |
| GET/POST | `/v1/tenants/{id}/categories` | member / owner | the menu's sections, in reading order |
| PATCH/DELETE | `/v1/tenants/{id}/categories/{category_id}` | owner | rename, re-order, hide or remove one |
| GET | `/v1/tenants/{id}/menu/items` | member | the menu's items, by section and rank |
| GET | `/v1/tenants/{id}/menu/options` | member | what the item form offers (the lists the model validates against) |
| POST | `/v1/tenants/{id}/menu/items` | owner | add a dish by hand |
| POST | `/v1/tenants/{id}/menu/images` | owner | upload a picture; returns the URL to put on an item |
| POST | `/v1/tenants/{id}/menu/availability` | owner | turn dishes on or off, by id or by whole section |
| PATCH/DELETE | `/v1/tenants/{id}/menu/items/{item_id}` | owner | edit or remove one |
| POST | `/v1/tenants/{id}/menu/import` | owner | read a POS export (`dry_run=true`) or make it the menu |
| GET | `/v1/images/{image_id}` | anyone | a stored menu picture, until a CDN serves them — public, the diner's menu shows them |
| GET | `/v1/public/restaurants/{id}/menu?table=` | anyone | the menu as the table sees it: available dishes, narrow projection, the table if named |
| POST | `/v1/public/restaurants/{id}/orders` | anyone | order from the table: seats it, adds the lines, sends the round as a `diner` KOT |
| GET/POST | `/v1/tenants/{id}/orders` | member | the floor (`scope=active`) or the day's closed orders; seat a table or open a takeaway |
| GET | `/v1/tenants/{id}/orders/{order_id}` | member | one order with its lines and totals |
| POST | `/v1/tenants/{id}/orders/{order_id}/lines` | member | add dishes, pending for the kitchen |
| PATCH/DELETE | `/v1/tenants/{id}/orders/{order_id}/lines/{line_id}` | member | change quantity or note, or take a pending line off |
| POST | `/v1/tenants/{id}/orders/{order_id}/kot` | member | send what is pending to the kitchen as a numbered ticket |
| GET | `/v1/tenants/{id}/orders/{order_id}/kots`, `/v1/tenants/{id}/kots/{kot_id}` | member | the tickets an order has sent; one ticket for reprinting |
| GET | `/v1/tenants/{id}/kots` | member | the kitchen's queue: unacknowledged tickets of orders still on the floor |
| POST | `/v1/tenants/{id}/kots/{kot_id}/acknowledge` | member | the kitchen has seen it; idempotent |
| POST | `/v1/tenants/{id}/orders/{order_id}/bill`, `/close`, `/cancel` | member | print the bill; mark it paid; abandon it |
| GET/PATCH/DELETE | `/v1/tenants/{id}/members[/{user_id}]` | member / owner | the team |
| POST/GET/DELETE | `/v1/tenants/{id}/invites[/{invite_id}]` | owner | invitations |
| GET | `/v1/users`, PATCH `/v1/users/{id}/role` | admin | platform roles |
| GET | `/v1/google-business/status`, `/connect`, `/callback`, `/locations` | signed in | the Business Profile connection and its businesses |
| POST | `/v1/google-business/import`, `/sync` | signed in / owner | import a business; refresh an imported one |
| DELETE | `/v1/google-business/connection` | signed in | revoke and forget the grant |

Errors: 404 `Unknown agent '<name>'`, 422 for validation failures, 504 `Agent timed out`,
500 `Agent execution failed`. Tracebacks are logged, never returned. Interactive docs live
at `/api/docs` and `/api/redoc`.

The event stream already emits `agent_started`, `tool_started`, `tool_completed`,
`agent_completed` and `agent_failed`, with `token` available for token streaming. The chat
UI still uses the plain request, so live execution can be switched on without touching the
agent package.

---

## Production deployment

One Elastic Beanstalk environment, one EC2 instance, one domain:

```
https://example.com
        │
   host nginx (Elastic Beanstalk)
        │
   container :8080  ── nginx ──┬── /api/  → FastAPI  :8000 ── agents/
                               └── /      → Nuxt     :3000
```

`Dockerfile` builds both applications and runs nginx, uvicorn and the Nuxt server under
supervisord in the final stage, as a non-root user. Build and run it locally with:

```bash
docker build -t menu-hero-core .
docker run --rm -p 8080:8080 -e SECRET_KEY=change-me menu-hero-core
```

Deploy with the EB CLI on the Docker platform:

```bash
eb init -p docker -r <region> menu-hero-core
eb create --single --instance-types t3.small menu-hero-prod
eb setenv SECRET_KEY=… DATABASE_URL='mongodb+srv://…' LLM_API_KEY=…
eb deploy
eb open
```

`docker-compose.yml` is excluded through `.ebignore`: if it reaches the bundle, Elastic
Beanstalk switches to Docker Compose mode and stops managing nginx. Full instructions,
including MongoDB Atlas and HTTPS, are in [`deploy/README.md`](deploy/README.md).

---

## Evolution roadmap

The architecture is arranged so each of these is an addition, not a rewrite.

| Goal | What to change |
|------|----------------|
| Queue and workers | Add a `QueuedAgentExecutor` implementing the `AgentExecutor` protocol in `backend/app/services/agent_service.py`, and a worker process in `workers/` that calls the same `agents.run_agent()`. `AgentRequest` and `AgentResult` are already Pydantic, so they serialise as they are. The agent package learns nothing about the queue. |
| Live execution in the UI | Consume `POST /api/agents/stream` from `useAgent()`; the event union is already in `frontend/types/api.ts`. |
| Real LLM providers | Add `agents/integrations/openai.py` (or anthropic, google) implementing `LLMClient`, register it in `PROVIDER_FACTORIES`, and set `LLM_PROVIDER`. |
| More agents and tools | Subclass `BaseAgent` in `agents/implementations/`, or `BaseTool` in `agents/tools/`, then register in `agents/core/registry.py`. |
| Persistence | Define a `MongoDocument` and a `MongoRepository` in `backend/app/models/`, and expose it to agents through a service interface rather than the document class. |

---

## Verification

Everything below was executed against this repository, not merely configured.

| Check | Result |
|-------|--------|
| `agents` test suite | 82 passed, no FastAPI imported |
| `backend` test suite | 73 passed, including 2 against a live MongoDB 8 |
| ruff and mypy `--strict`, both packages | clean |
| `npm run typecheck`, `npm run build` | clean |
| Full path through the Nuxt dev server | `POST /api/agents/run` returned `Processed: Analyze this information` |
| Same path through the built Nuxt server | identical result |
| Production image, default target | built, container healthy, `/`, `/agent` and `/api/agents/run` all served on one port |
| MongoDB from inside the image | ping and write succeeded |
| `docker compose up` | MongoDB, backend and frontend healthy; agent run and MongoDB write through the stack |
| Boundary audit | no web-framework import in `agents/`; no backend host or secret in the browser bundle |
