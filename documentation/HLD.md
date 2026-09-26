# MenuHero — High-Level Design

**Version:** 1.3 (v1 scope)
**Status:** Approved for low-level design
**Owner:** Vinod
**Depends on:** Product one-pager (locked), JSON menu schema (contract; locked before LLD)
**License:** AGPL-3.0

**Changes from 1.2:** identity is split from tenancy — `users` becomes a global, password-less Google identity with a platform role (`admin`/`user`), and the tenant role (`owner`/`staff`) moves to a new `memberships` collection; management-app auth is Google OIDC with server-side sessions and email-matched invites (see 3.1).

**Changes from 1.1:** MongoDB replaces PostgreSQL/pgvector as the single datastore; retrieval uses MongoDB Vector Search + MongoDB Search with `$rankFusion`; the separate SAFETY path is removed in favour of a single retrieval path with structured constraint extraction; POS-export mapper and enrichment/allergen-inference stages added to ingestion; tenancy enforcement moves from RLS to a repository layer with indexed filter fields.

---

## 1. Overview

MenuHero converts real-world restaurant menus (phone photos, PDFs, POS exports) into a structured, versioned menu model and serves it through a QR digital menu, a streaming AI chat assistant, a mini-POS with KOT generation, and an MCP server for external agents.

The system is a **Python modular monolith** deployed as two runtime roles (API and worker) over a single **MongoDB** replica set with native vector and full-text search. All LLM interaction is mediated through a typed agent harness with one retrieval path, hard metadata filters for dietary constraints, inline guardrails, and offline eval gates in CI.

### 1.1 Goals
- Ingest a menu to a published, searchable state in under 3 minutes (excluding human review).
- Apply veg/non-veg and price constraints as **hard filters** in retrieval — never left to the model's reading of item text.
- Answer allergen questions from a per-item field populated and reviewed at ingestion, quoted by the model, never inferred at query time; every allergen answer directs the diner to confirm with staff.
- Recommend dishes from natural-language questions ("something light and tangy", "what's good for two people") using retrieval over enriched item documents, constrained by the diner's stated diet and budget.
- Upsell at the right moments — after a cart change and before order confirmation — with suggestions that are in stock, diet-compatible with the cart, and governed by tenant-configured rules, so the model phrases the suggestion but never chooses it.
- Let a seated diner go from question → cart → order → KOT without leaving the chat.
- Expose the same capabilities to external agents over MCP.
- Enforce quality with two CI-gated eval suites (extraction, chat) and online guardrails.

### 1.2 Non-goals (v1)
Payments, voice ordering, personalization from order history, self-serve signup, quantity-based inventory, verified allergen certification.

---

## 2. Architecture

### 2.1 Context

```
  Diner (QR, table token) ──┐
  Staff / Owner (login) ────┼──► MenuHero ◄──── External AI agents (MCP, API key)
                            │        │
                            │        ├── LLM providers (primary + fallback)
                            │        ├── Object storage (raw uploads, KOT renders)
                            │        └── MongoDB replica set + mongot (search)
```

### 2.2 Logical components

```
┌──────────────────────────────┐      ┌──────────────────────────────┐
│         Diner Web App        │      │     Management Web App       │
│  browse · chat (SSE) · cart  │      │ login · upload · review ·    │
│                              │      │ menu editor · order board ·  │
└──────────────┬───────────────┘      │ KOT · 86 toggle              │
               │ HTTPS / SSE          └──────────────┬───────────────┘
               │                                     │ HTTPS
┌──────────────▼─────────────────────────────────────▼───────────────┐
│                    menuhero-api  (FastAPI, Python)                  │
│                                                                    │
│  ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌────────────────┐   │
│  │ Auth &     │ │ Menu       │ │ Order      │ │ Agent Harness  │   │
│  │ Tenancy    │ │ Service    │ │ Service    │ │ (Pydantic AI)  │   │
│  │ users ·    │ │ versions · │ │ cart ·     │ │ constraint     │   │
│  │ roles ·    │ │ publish ·  │ │ orders ·   │ │ extraction ·   │   │
│  │ tokens ·   │ │ stock flag │ │ KOT        │ │ tools · guards │   │
│  │ API keys   │ └────────────┘ └────────────┘ └───────┬────────┘   │
│  └────────────┘                               ┌───────▼────────┐   │
│  ┌────────────┐                               │ Retrieval Svc  │   │
│  │ MCP Server │◄──────────────────────────────┤ $rankFusion ·  │   │
│  │ (FastMCP)  │                               │ rerank         │   │
│  └────────────┘                               └────────────────┘   │
│  ┌────────────────────────────────────────────────────────────┐    │
│  │ Repository layer — every query tenant-scoped by construction│    │
│  └────────────────────────────────────────────────────────────┘    │
└──────────────┬─────────────────────────────────────┬───────────────┘
               │ jobs collection (atomic claim)       │
┌──────────────▼───────────────┐      ┌──────────────▼───────────────┐
│     menuhero-worker          │      │  MongoDB 8.2+ replica set    │
│  ingestion pipeline ·        │◄────►│  + mongot ×2 (Lucene index)  │
│  enrichment · indexing ·     │      │  menus · items · orders ·    │
│  scheduled jobs · eval runs  │      │  kots · chats · jobs · evals │
└──────────────┬───────────────┘      └──────────────────────────────┘
               │
       Object storage (S3-compatible)          Langfuse (self-hosted)
```

Both runtime roles ship from the same codebase and image; the role is selected by entrypoint. Service modules are importable packages with explicit interfaces; the harness and MCP server call them in-process.

### 2.3 Technology

| Layer | Choice |
|---|---|
| Language / runtime | Python 3.12, `uv` |
| API | FastAPI, Uvicorn, Pydantic v2 |
| Agent harness | Pydantic AI (typed tools, structured outputs, streaming, OTel) |
| MCP | FastMCP, Streamable HTTP transport, mounted on the API |
| Database | MongoDB 8.2+ Community, 3-node replica set, `mongot` for `$search` / `$vectorSearch` / `$rankFusion` |
| Driver / models | PyMongo async driver; Pydantic models as the document schema; no ODM |
| Job queue | `jobs` collection, atomic `findOneAndUpdate` claim with lease |
| Object storage | S3-compatible (Cloudflare R2) |
| OCR | PaddleOCR (local) |
| Embeddings | Configurable provider; dimension pinned per index |
| Reranker | Local cross-encoder (`bge-reranker` class) |
| LLMs | Two providers configured; per-task model selection (constraint extraction, extraction, enrichment, generation) |
| Observability | OpenTelemetry → Langfuse (LLM spans) + Prometheus/Grafana (service metrics) |
| Frontend | Static SPA bundles (diner, management), served via CDN |
| Infra | Kubernetes, single region; MongoDB Controllers for Kubernetes Operator for `mongod` + `mongot`; marketing site on Cloudflare Pages |

---

## 3. Component specifications

### 3.1 Auth & Tenancy
- **Responsibilities:** tenant lifecycle (operator-created; no self-serve), identity and roles, session auth for the management app, **table tokens** for diners, **API keys** for MCP clients.
- **Identity:** Google OIDC (authorization-code flow) only; no passwords. The `id_token` signature is verified against Google's JWKS with pinned algorithms, and `iss`/`aud`/`exp`/`sub` validated, before any claim is trusted. A `users` document is a *person* — global, keyed on the Google subject and the verified email — and carries a platform role (`admin` | `user`). Everyone who signs in is a `user`; the first `admin` comes from a bootstrap environment variable, every later one from the role-change API.
- **Membership:** a `memberships` document grants one person one role (`owner` | `staff`) at one tenant, so identity exists before (and independently of) any restaurant, and one person can be owner of one tenant and staff at another. Effective role for portal routing is the strongest held: `admin` > `owner` > `staff` > `user`.
- **Sessions:** opaque random token in an `HttpOnly`, `SameSite=Lax` cookie; only its SHA-256 digest is stored, and the `sessions` document holds nothing but `user_id`, so roles are resolved per request and a role change or logout takes effect immediately. 30-day TTL index.
- **Invites:** an invite is a *pending membership* addressed to an email, not a credential. It is consumed when the invited person signs in with a Google account whose verified email matches, so a leaked link grants nothing on its own.
- **Table token:** signed, short-lived, rotated per seating, encodes `tenant_id` + `table_id`. Possession is the presence model.
- **Tenancy enforcement:** a `TenantContext` is resolved per request and injected into the repository layer. Repositories expose no query method that does not take a `TenantContext`; every filter is built with `tenant_id` first. Search indexes declare `tenant_id` as a filter field so `$vectorSearch` and `$search` pre-filter by tenant inside the index. A CI lint fails any raw collection access outside the repository package.

### 3.2 Menu Service
- **Responsibilities:** menu versions, categories, items with embedded variations and addon groups, dietary attribute, availability flag (`is_available`, reason, auto-reset at day close), publish/rollback.
- **Contract:** the JSON menu schema. Items are stored as documents in the shape of the schema; no relational projection.
- **Versioning:** each publish writes a new immutable `menu_versions` document and a new set of `items` documents tagged with `menu_version`; the tenant's `live_version` pointer is swapped last. Diner UI, retrieval, and MCP read only `menu_version == live_version`. Publish enqueues `index_menu`; the version carries `index_status: pending | indexed`, and the live pointer swap waits for `indexed` so search never serves a half-built version.

### 3.3 Order Service
- **Responsibilities:** carts bound to a table token, cart lines with variation/addon selections, order placement, status (`placed → in_kitchen → served → closed`), KOT generation, staff order board feed.
- **Chat, as built:** the diner page's *Chat & order* is the agent's seat; today it is filled by a client-side menu search that reads diet and budget from the question and answers with dishes (`frontend/composables/useMenuAssistant.ts`). The UI contract - a question in, a sentence and dishes out - is what 3.6 replaces it with.
- **As built (the table's own path):** `POST /public/restaurants/{id}/orders` is the diner flow without a cart document - the phone holds the round and sends it whole. It seats the table (idempotent), adds lines at today's prices and writes a KOT with `source=diner` in one call; no session, no diner identity stored (HLD 8). `carts` and the table-token flow remain for the agent path.
- **As built (staff POS first):** the till in the management app writes orders directly — no cart, since staff tap dishes onto the ticket. Status is `open → billed → closed` (+ `cancelled`); the diner-facing `placed → in_kitchen → served` states arrive with the table-token flow and map onto the same document. Lines carry a `kot_id` once sent; pending lines are the only editable ones. Seating is idempotent per table via a partial unique index on open orders; takeaways use a client-minted `idempotency_key`. Prices and names are snapshotted onto the line. No tax line yet — total equals subtotal until a GST rate exists on the tenant.
- **Single writer:** all order mutations go through this service. Harness and MCP call it with an idempotency key; a unique index on `{tenant_id, idempotency_key}` makes duplicates impossible. Placement runs in a multi-document transaction (cart → order → KOT).
- **KOT:** structured record plus rendered HTML/PDF in object storage; grouped by station if configured.
- **Checkout:** stops at KOT; pay-at-counter only.

### 3.4 Ingestion Pipeline (worker)
Job chain; each stage idempotent and re-runnable. Two entry routes converge at `validate`.

```
image/PDF: store_raw → preprocess → extract → attest ─┐
POS export: store_raw → map_pos ──────────────────────┼─► validate → enrich → [review] → publish → index
```

| Stage | Description |
|---|---|
| `store_raw` | Persist original to object storage; create `extraction_jobs` document. |
| `preprocess` | Images: orientation, deskew, contrast. PDFs: page split, embedded-text extraction. |
| `extract` | Vision-capable model, temperature 0, JSON schema as output contract, one call per page; page results merged and de-duplicated. |
| `attest` | OCR the same page; every extracted item name and price must fuzzy-match OCR text. Unmatched fields flagged `needs_review`. Confidence derives from attestation, not model self-report. |
| `map_pos` | Deterministic column mapper per POS format (Petpooja-style first). Rules: parent price `0` with variations → `price_min`/`price_max` from variations; `Attributes` → `diet`; `Parent_Category`/`Category`/`Category_online_display` reconciled to one category path with a fallback order; combo names split on `+` into `components`; wide variation/addon column groups folded into embedded arrays; ingredient-list names shortened with the long form kept as description. Unmappable rows flagged. |
| `validate` | JSON schema validation + business rules (price ≥ 0 or variations present, unique names per category, currency, `diet ∈ {veg, non-veg, egg}`). |
| `enrich` | One small-model call per item, structured output, temperature 0: generated description when missing (`description_generated: true`), cuisine/flavour/spice/portion/occasion tags (e.g. `light`, `tangy`, `sharing`, `mild`), `pairs_with` tags (dish types and categories it complements, used by upsell), component glossary (e.g. "neer dosa: thin rice-batter crepe"), and **`allergens_inferred`** from the controlled vocabulary (EU 14 ∪ FSSAI) with a one-line basis. Output validated against the vocabulary; anything outside it is dropped. Enrichment text is stored separately from source text. |
| `review` | Management app shows the draft with flags and inferred allergens per item; owner accepts/corrects. Mandatory before a tenant's first publish; flagged-only thereafter. Corrections stored and fed to the extraction eval dataset. Owner-confirmed allergens set `allergens_reviewed: true`. |
| `publish` | Menu Service writes the new version (see 3.2). |
| `index` | Builds `search_text` (name + category path + components + description + enrichment) and the embedding for each item; writes them onto the item document. `mongot` picks up changes via change streams and updates the Lucene index; the worker polls index readiness and sets `index_status: indexed`. |

### 3.5 Retrieval Service
- **Input:** `TenantContext`, query text, structured filters (`diet`, `price_max`, `category`, `available_only`).
- **Pipeline:** one aggregation: `$rankFusion` over a `$vectorSearch` sub-pipeline (embedding of query text, `numCandidates` ≈ 20×k) and a `$search` sub-pipeline (BM25 on `name`, `components`, `search_text` with fuzzy matching for transliterated dish names) → top-k fused → local cross-encoder rerank → top-n item documents.
- **Filters:** applied as index filter fields inside both sub-pipelines (`tenant_id`, `menu_version`, `diet`, `price_min`, `is_available`), never as a post-`$match` — this keeps recall intact and makes cross-tenant results structurally impossible.
- **Unit of retrieval:** whole item documents, never text chunks. The model receives the item's structured fields (`price`, `diet`, `allergens_inferred`, `allergens_reviewed`, `variations`, `is_available`) alongside its text.
- **Index definitions:** one vector index (`embedding`, cosine, dimension pinned; filter fields as above) and one search index (analyzers for `name`/`components`/`search_text`, `tenant_id` and `menu_version` as token fields) per `items` collection. Definitions are versioned in the repo and applied by migration.

### 3.6 Agent Harness
Stateless per turn. Conversation state lives in `chat_sessions` keyed on table token.

```
turn ─► input guards ─► load context ─► constraint extraction ─► retrieval ─► generation ─► output guards ─► SSE
                                                                            └─► tools (cart, order, status)
```

**Context per turn:** tenant, table, live version, cart, last N turns, and the tenant profile (3.8) — persona block in the system prompt, item-linked talking points merged onto retrieved items, signature/best-seller boosts in retrieval.

**Constraint extraction:** small model, structured output:
`{intent: browse | order | status | out_of_scope, diet: veg | non-veg | egg | any, price_max, category, query_text, allergen_asked: [...], confirms_order: bool}`.
`diet` and `price_max` become retrieval filters; the model downstream never re-derives them from item text.

**Single retrieval path:** every `browse` turn (including allergen questions) runs retrieval with the extracted filters and generates from the returned item documents only.

**Generation rules (system prompt + output contract):**
- Answer only from returned items; cite item IDs for every factual claim.
- Prices, `diet`, and availability are quoted from fields, not inferred from text.
- Allergen questions: quote `allergens_inferred`; if `allergens_reviewed` is false, say it is based on typical preparation; always append the confirm-with-staff line; never describe an item as "safe" for an allergy.
- Emit item cards and follow-up chips as structured blocks.

**Tools (typed via Pydantic; same schemas exported to MCP):**
`search_menu`, `get_item`, `get_allergen_info`, `add_to_cart`, `remove_from_cart`, `view_cart`, `place_order(cart_id, confirm)`, `suggest_followups`, `get_order_status`.

**Order gating:** `place_order` executes only when `confirms_order` is true for the current turn and the cart is non-empty; idempotency key = hash(table token, cart version).

**Recommendations:** a `browse` turn with a descriptive query ("light and tangy", "good for sharing", "not too spicy") is retrieval over `search_text`, where the `enrich` stage has already written flavour, spice, portion, and occasion tags per item. The model ranks and explains from the returned items only, citing IDs; it does not recommend anything it did not receive. Group-size and occasion hints from constraint extraction become soft boosts, not filters.

**Upsell / follow-ups:** a deterministic post-step, not a model freedom. Triggers: after any cart change, and once before order confirmation. `suggest_followups` runs a "pairs with" retrieval seeded by the cart's items and their `enrichment.pairs_with` tags, filtered by `is_available`, the cart's `diet`, and the tenant's upsell rules (`settings.upsell`: allowed categories, max suggestions, price band, excluded items, cooldown per session). Candidates are ranked by pairing score with a tie-break toward tenant-flagged priority items. The model phrases the suggestion from the returned candidates and emits them as chips; it does not select, add, or invent. Acceptance is logged per suggestion for demand analytics.

**Streaming:** SSE. Events: `token`, `card`, `tool_call`, `tool_result`, `replace`, `done`, `error`. `done` is withheld until output guards pass; a guard rewrite emits `replace`.

### 3.7 MCP Server
- Mounted at `/mcp` on `menuhero-api`, Streamable HTTP transport.
- **Auth:** per-tenant API key (hashed at rest); write tools additionally require a table token.
- **Tools:** `search_menu`, `get_item`, `get_allergen_info`, `get_order_status`, `get_stock_status`, `add_to_cart`, `place_order`.
- Schemas generated from the same Pydantic models as the harness tools.

### 3.8 Tenant Context (restaurant profile)
Every tenant has a structured profile that shapes how the assistant talks, what it favours, and what it must not say. It is collected during onboarding in the management app, editable by the owner, versioned, and injected into every chat turn.

**Profile (`tenants.profile`)**

| Field | Content | Used by |
|---|---|---|
| `story` | Background, cuisine, region, what the place is known for (2–4 sentences) | System prompt persona block |
| `voice` | Tone (warm / crisp / playful), language(s), forms of address, phrases to use or avoid | System prompt |
| `talking_points[]` | Owner-authored lines about the restaurant or specific items ("our ghee roast is a 40-year-old family recipe") linked to `item_id` where item-specific | Generation: item-linked lines are attached to the retrieved item document; general lines go in the persona block |
| `signature_items[]` | Owner-chosen items to lead with | Retrieval soft boost; recommendation and upsell tie-break |
| `best_sellers[]` | Seeded manually at onboarding; refreshed weekly from aggregate order data (tenant-level, not per diner) | Retrieval soft boost; "what's popular" answers quote this list |
| `house_rules[]` | Things staff would say: preparation times, no substitutions, spice-level policy, sharing sizes, last-order time | Generation; also returned by `get_item` where item-linked |
| `service_context` | Service style (counter / table), stations, current specials with validity window | Generation, upsell |
| `do_not_say[]` | Claims the owner forbids (e.g. "never call anything organic") | Output guard rewrite list |
| `upsell` | Rules from 3.6 | `suggest_followups` |

**How it enters a turn**
- `story`, `voice`, general `talking_points`, `house_rules`, `service_context` are rendered into a persona block of the system prompt, capped in length, with the profile version recorded on the trace.
- Item-linked `talking_points` and `house_rules` are merged onto retrieved item documents at retrieval time, so the model sees them next to the item and can cite them by ID like any other field.
- `signature_items` and `best_sellers` are applied as post-fusion score boosts (bounded, configurable) rather than filters — a boost cannot surface an item that fails `diet`, `price`, or `is_available`.
- "What's popular / what do you recommend" with no other constraint answers from `best_sellers` ∩ available, phrased by the model.

**Best-seller refresh:** a weekly `refresh_best_sellers` job aggregates `orders.lines` per tenant over a trailing window, writes the top-N item IDs with counts to `profile.best_sellers`, and keeps the owner-seeded list as a fallback until enough orders exist. This is tenant-level demand data and stays within the "no per-diner personalization" boundary.

**Trust boundary:** the profile is tenant-authored content and is treated as data, not instructions. It is rendered into clearly delimited prompt sections, scanned for injection patterns on save (rejected with a message to the owner), and cannot override system rules — a talking point cannot, for example, disable the allergen staff-confirmation line.

### 3.9 Web apps
- **Diner:** mobile-first SPA. Browse (category → item → variations/addons → cart) and chat on one screen; chat renders cards from SSE events. All calls carry the table token.
- **Management:** SPA behind login. Upload + review (including inferred-allergen confirmation), menu editor, order board (5 s polling in v1), KOT view/print, 86 toggle, staff management.

---

## 4. Data architecture

Single MongoDB database, one collection set shared by all tenants; every tenant-scoped document carries `tenant_id` as the first key of every compound index. Raw uploads and KOT renders in object storage.

**Collections**

| Collection | Key fields | Notes |
|---|---|---|
| `tenants` | `_id`, `slug`, `profile` (story, voice, talking_points, signature_items, best_sellers, house_rules, service_context, do_not_say, upsell — see 3.8), `profile_version`, `settings` (stations, hours), `live_version`, `pos{billing}` (off: the POS is the KOT board only, no order can be opened) | |
| `users` | `email`, `google_sub`, `name`, `picture`, `platform_role: admin\|user`, `is_active`, `last_login_at` | global identity, no tenant; unique `google_sub`, unique `email` |
| `memberships` | `tenant_id`, `user_id`, `role: owner\|staff`, `invited_by` | unique `{tenant_id, user_id}`; index `{user_id}` |
| `sessions` | `user_id`, `token_hash`, `expires_at`, `last_seen_at`, `user_agent` | unique `token_hash`; TTL on `expires_at` |
| `invites` | `tenant_id`, `email`, `role`, `token_hash`, `invited_by`, `expires_at`, `accepted_at` | unique `token_hash`; unique `{tenant_id, email}` while pending |
| `tables` | `tenant_id`, `label`, `label_key`, `seats`, `is_active`, `current_token_hash` | unique `{tenant_id, label_key}`; identity only — geometry lives on the floor plan. Taken off a floor plan it is deactivated, never deleted, so past orders and printed QR codes still resolve |
| `floor_plans` | `tenant_id`, `width`, `height`, `elements[]` (`id`, `kind: table\|wall\|text`, `shape`, `table_id`, `text`, `x`, `y`, `width`, `height`, `rotation`) | unique `tenant_id` — one plan per restaurant. A drawing, replaced whole on every save; a `table` element points at `tables` rather than containing one |
| `api_keys` | `tenant_id`, `key_hash`, `scopes` | |
| `categories` | `tenant_id`, `name`, `name_key`, `rank`, `status: active\|hidden` | unique `{tenant_id, name_key}`; index `{tenant_id, rank}`. The editable list of menu sections an owner maintains — an item's published section stays denormalised as `category_path` on the item |
| `menu_items` | `tenant_id`, `name`, `online_name`, `category`, `diet`, `price`, `packing_charges`, `profit_margin`, `weight`/`weight_unit`, `gst_type`, `order_types[]`, `expose_in[]`, `allow_decimal_quantity`, `manufactured_on`, `expires_on`, `variations[]`, `addon_group`, `short_code`, `short_code_2`, `hsn_code`, `image_url`, `rank`, `is_available` | the *editable* working copy an owner maintains and an import writes; `items` below stays the immutable published projection, tagged with `menu_version` |
| `menu_images` | `tenant_id`, `digest` (SHA-256), `content_type`, `size`, `data` | unique `{tenant_id, digest}` — content-addressed, so one placeholder repeated across a whole import is stored once. A **bridge until a CDN exists**: items store only `image_url`, so swapping `services/image_store.py` moves the bytes and changes no document |
| `menu_versions` | `tenant_id`, `version`, `status: draft\|indexed\|live\|archived`, `index_status`, `source_job_id` | |
| `items` | `tenant_id`, `menu_version`, `item_id` (stable across versions), `name`, `category_path`, `components[]`, `description`, `description_generated`, `enrichment{}`, `search_text`, `embedding`, `diet`, `price_min`, `price_max`, `variations[]`, `addon_groups[]`, `allergens_inferred[]`, `allergens_reviewed`, `is_available`, `unavailable_reason` | unique `{tenant_id, menu_version, item_id}`; vector + search indexes |
| `allergen_vocabulary` | `code`, `labels[]`, `region` | global |
| `carts` | `tenant_id`, `table_token_hash`, `version`, `lines[]` | |
| `orders` | `tenant_id`, `number`, `kind: dine_in\|takeaway`, `table_id`, `table_label`, `status: open\|billed\|closed\|cancelled`, `lines[]` (`id`, `item_id`, `name`, `variation`, `quantity`, `unit_price`, `note`, `kot_id`, `added_at`), `kot_ids[]`, `idempotency_key`, `opened_by`, `billed_at`, `closed_at` | unique `{tenant_id, number}`; partial unique `{tenant_id, table_id}` where `status=open` (one open order per table); partial unique `{tenant_id, idempotency_key}`; `{tenant_id, status}` for the floor |
| `kots` | `tenant_id`, `order_id`, `number`, `order_number`, `kind`, `table_label`, `lines[]`, `source: pos\|diner`, `sent_by`, `sent_by_name`, `sent_at`, `acknowledged_at`, `acknowledged_by` | `{tenant_id, order_id}`; `source=diner` reserved for the QR flow; acknowledged once, never cleared; rendered in the browser for an 80 mm printer — `station`/`render_url` wait for kitchen routing |
| `sequences` | `tenant_id`, `name: order\|kot`, `value` | unique `{tenant_id, name}`; `$inc` on upsert gives gap-free, human numbers per restaurant |
| `extraction_jobs` | `tenant_id`, `source_type`, `raw_url`, `stage`, `draft{}`, `flags[]` | |
| `review_corrections` | `tenant_id`, `job_id`, `item_id`, `field`, `before`, `after` | feeds eval datasets |
| `chat_sessions` | `tenant_id`, `table_token_hash`, `turns[]` (constraints, retrieved_ids, tool_calls, guard_results, trace_id) | TTL index for purge |
| `jobs` | `type`, `payload`, `status`, `lease_until`, `attempts` | atomic claim |
| `eval_datasets`, `eval_runs` | cases, model pins, scores, per-case results | |

**Consistency notes**
- Transactional writes (order placement, publish pointer swap) use replica-set transactions.
- Search indexes are eventually consistent; `index_status` gates the live pointer so a version is never live before it is searchable.
- `embedding` dimension is pinned in the index definition; changing embedding models requires a new index name and a full re-index job.

---

## 5. Interfaces

### 5.1 Public HTTP

| Area | Endpoints (representative) |
|---|---|
| Auth | `GET /v1/auth/google`, `GET /v1/auth/google/callback`, `GET /v1/auth/me`, `POST /v1/auth/logout`, `POST /v1/auth/invites/accept`, `POST /tables/{id}/token` |
| Team | `POST /v1/tenants`, `GET /v1/tenants`, `GET/PATCH/DELETE /v1/tenants/{id}/members[/{user_id}]`, `POST/GET/DELETE /v1/tenants/{id}/invites[/{invite_id}]`, `GET /v1/users`, `PATCH /v1/users/{user_id}/role` |
| Menus | `POST /menus/upload`, `GET /menus/{v}/draft`, `POST /menus/{v}/review`, `POST /menus/{v}/publish`, `GET /menu` (live, diner) |
| Items | `PATCH /items/{id}`, `POST /items/{id}/availability` |
| Cart & orders | `GET/POST /cart`, `POST /orders`, `GET /orders/{id}`, `GET /orders/board` |
| Diner (built) | `GET /public/restaurants/{id}/menu?table=`, `POST /public/restaurants/{id}/orders` — no session; the QR page at `/restaurant/{id}/order?table=` |
| Staff POS (built) | `GET/POST /tenants/{id}/orders`, `…/orders/{id}/lines[/{line_id}]`, `…/orders/{id}/kot`, `…/orders/{id}/bill\|close\|cancel`, `…/kots` (the kitchen's queue: unacknowledged tickets of active orders), `…/kots/{kot_id}`, `…/kots/{kot_id}/acknowledge` |
| Chat | `POST /chat` → `text/event-stream` |
| Health | `GET /healthz`, `GET /readyz` (checks `mongod` and search readiness) |

### 5.2 MCP
`/mcp` — Streamable HTTP; tool list in 3.7.

### 5.3 Internal
Services are Python packages behind the repository layer. The `jobs` collection is the only async boundary (`ingest_menu`, `index_menu`, `reset_availability`, `refresh_best_sellers`, `run_eval`).

---

## 6. Key flows

### 6.1 POS export ingestion
1. Owner uploads the export → `POST /menus/upload` → raw stored → `ingest_menu` job.
2. Worker: `map_pos` → `validate` → `enrich` (descriptions, tags, `allergens_inferred`).
3. Review screen shows mapped items, flags, and inferred allergens; owner confirms/corrects.
4. Publish → new version (`index_status: pending`) → `index_menu` → embeddings written → `mongot` syncs → `index_status: indexed` → live pointer swapped.

### 6.2 Photo/PDF ingestion
Same as 6.1 with `preprocess → extract → attest` in place of `map_pos`.

### 6.3 Allergen question
"Does the chicken gasi have nuts?" → constraint extraction `{intent: browse, allergen_asked: [nuts], query_text: "chicken gasi"}` → retrieval (BM25 catches the exact name; vector handles paraphrase) → top item → generation quotes `allergens_inferred` (`[coconut, dairy?]` → "no tree nuts listed; contains coconut") with the reviewed/unreviewed qualifier and the confirm-with-staff line → output guard verifies the claim against the item's field → stream.

### 6.4 Discovery → order → KOT
1. "Something tangy and veg under 200" → `{diet: veg, price_max: 200, query_text: "tangy"}`.
2. `$rankFusion` with filters `diet=veg, price_min<=200, is_available=true` → rerank → top 3.
3. Generation cites item IDs → output guard verifies prices and diet against fields → cards streamed.
4. "Add the first one" → `add_to_cart` → `suggest_followups` → chips.
5. "That's it, order" → `confirms_order: true` → `place_order` (idempotent, transactional) → order + KOT → board updates → diner sees order number.

### 6.5 External agent via MCP
API key → `get_stock_status` → `search_menu` (unavailable items filtered in-index) → `add_to_cart` / `place_order` only with a table token.

---

## 7. Evals and guardrails

### 7.1 Extraction quality gate (pre-build, CI)
- **Dataset:** 15 real menus (photos + PDFs; ≥3 multi-language, ≥2 handwritten/stylized) plus 3 POS exports, hand-labelled in the JSON schema.
- **Metric:** weighted field accuracy — name 0.30, price 0.30, category 0.15, diet 0.15, description 0.05, variations/addons 0.05. **≥ 90%.**
- **Hard constraint:** zero true hallucinations (any item, price, or variation not on the source fails the run).
- **POS mapper:** exact-match tests per format; 100% on the labelled exports.
- **Gate:** no harness, POS, or MCP code starts until this passes.

### 7.2 Enrichment eval (post-gate, CI)
- `allergens_inferred` precision/recall against a hand-labelled subset (~100 items). Target recall ≥ 0.9 for the major allergens; precision reported. Generated descriptions judged for factual restraint (no invented ingredients).

### 7.3 Chat eval set (post-gate, CI)
~150 cases over 3 published menus, grown from review corrections and flagged production traces.

| Category | Check | Target |
|---|---|---|
| Constraint extraction | `diet`, `price_max`, `confirms_order` extracted correctly | Diet 100% (gate), others ≥ 0.95 |
| Filter correctness | No returned item violates a hard filter | 100% (gate) |
| Grounding | Every price/diet/allergen claim matches the item field | 100% (gate) |
| Allergen phrasing | Quotes the field; unreviewed qualifier present when applicable; staff line present; never "safe" | 100% (gate) |
| Retrieval | Labelled relevant item in top-3 (includes transliterated-name cases) | Recall@3 ≥ 0.9 |
| Refusal | Off-topic, injection, medical-assurance requests | Judge rubric, ≥ 0.95 |
| Recommendation relevance | For descriptive queries, top-3 contains a labelled acceptable item; explanation cites only returned IDs | Recall@3 ≥ 0.85; citation 100% |
| Upsell | Suggestions in stock, rule- and diet-compliant; never more than `max_suggestions`; cooldown respected | 100% (gate) |
| Profile adherence | Voice matches `voice`; item-linked talking points used when the item is discussed; `do_not_say` never appears | Judge rubric ≥ 0.9; `do_not_say` 100% |
| Tone | Helpfulness | Judge score, reported only |

### 7.4 Online guardrails (inline, layered)

| Layer | Check | On failure |
|---|---|---|
| Input | Valid table token, tenant resolved, per-token rate limit | 4xx |
| Input | Injection patterns | `out_of_scope` + log |
| Profile save | Injection patterns and instruction-like text in tenant profile fields | Rejected with owner-facing message |
| Input | Length / language sanity | Truncate or ask to rephrase |
| Retrieval | `tenant_id`, `menu_version`, `diet`, `is_available` as index filter fields | Structurally enforced |
| Tool | Argument schema validation; item IDs must exist in live version for tenant; quantity bounds | Structured error → one retry → apology |
| Tool | `place_order` requires `confirms_order` + idempotency key | Refused |
| Output | Claim verification of price, diet, availability, allergens against retrieved item fields | `replace` span, log |
| Output | Allergen answer must carry qualifier + staff line; "safe" rewritten | `replace` |
| Output | No PII echo, no other-tenant mention, no phrase from `do_not_say` | Rewrite |
| Model | System prompt constraints | Last line of defence |

### 7.5 Online monitoring
Per-turn trace (constraints, retrieved IDs, tool calls, guard outcomes, tokens, latency, cost) to Langfuse. Dashboards: filter-violation rate (should be 0), grounding-failure rate, guard-rewrite rate, allergen-question rate, p50/p95 per stage, cost per turn per tenant, search index lag. 5% of turns + 100% of guard failures sampled for review; promotable to the eval set.

---

## 8. Security

- **Tenancy:** repository layer is the only data access path; `TenantContext` mandatory; `tenant_id` first in every index; search filter fields include `tenant_id`; CI lint blocks raw collection access. No cross-tenant aggregation exists outside operator tooling.
- **Diner:** anonymous; table token only credential; short-lived, rotated per seating; no PII collected.
- **Staff/owner:** Google OIDC sign-in, opaque server-side sessions (digest at rest, 30-day TTL), role checks per endpoint resolved from the database on every request. No passwords are stored.
- **MCP:** API keys hashed; write tools require table token; per-key rate limits.
- **LLM boundary:** no model output persisted or acted on without schema validation; enrichment outputs validated against the allergen vocabulary; tool arguments validated against live data; prompts never include other tenants' data.
- **Database:** replica set with keyfile auth (required by `mongot`), TLS in-cluster, least-privilege users (`app`, `worker`, `migrator`), encrypted volumes.
- **Secrets:** Kubernetes secrets; provider keys rotated.
- **Retention:** `chat_sessions` TTL; raw uploads retained for re-extraction.

---

## 9. Deployment

```
Cloudflare (DNS, CDN, Pages for marketing + SPA bundles)
        │
Ingress (SSE-friendly timeouts, TLS)
        │
┌───────┴─────────────────────────────────────────────────────┐
│ Kubernetes (single region)                                  │
│  menuhero-api      ×2   (FastAPI + harness + MCP)           │
│  menuhero-worker   ×1–2 (ingestion, enrichment, index, eval)│
│  langfuse          ×1                                       │
│  MongoDB Controllers for Kubernetes Operator:               │
│    mongod  ×3 (replica set, keyfile auth)                   │
│    mongot  ×2 (search/vector index, sized independently)    │
└─────────────────────────────────────────────────────────────┘
        │
Object storage (R2)      LLM + embedding providers (primary, fallback)
```

- One image, two entrypoints. Config via environment; model names, thresholds, allergen vocabulary, POS mappings in config.
- Search and vector index definitions applied by migration and version-controlled.
- CI: lint (incl. repository-access lint), type-check, unit tests, index-definition check, **extraction gate**, **enrichment eval**, **chat eval gate**, image build.
- Rollout: rolling updates; migrations as a pre-deploy job.
- Backups: scheduled snapshots of `mongod` volumes plus oplog for point-in-time; search index is rebuildable from data and not backed up.

---

## 10. Non-functional requirements

| Concern | Target |
|---|---|
| Chat first token | ≤ 1.5 s p95 |
| Chat full turn | ≤ 5 s p95 |
| Retrieval (`$rankFusion` + rerank) | ≤ 200 ms p95 |
| Search index lag after publish | ≤ 30 s |
| Ingestion | ≤ 3 min for 4 pages, excluding review |
| Availability | 2 API replicas; 3-node replica set; snapshot + oplog backups |
| Cost | Per-turn, per-extraction, per-enrichment cost recorded; anomaly alert per tenant |
| Scale (v1) | ≤ 50 tenants, ≤ 5k items/tenant, ≤ 20 concurrent chats/tenant |

---

## 11. Build sequence

1. JSON schema — lock.
2. Ingestion pipeline (POS mapper first, then photo/PDF) + extraction eval harness → pass gate.
3. Auth & Tenancy, repository layer, Menu Service, publish/version/index-status.
4. Enrichment stage + enrichment eval; Retrieval Service with `$rankFusion` and index definitions.
5. Harness: constraint extraction → retrieval → generation → cart/order tools.
6. Chat eval set → gate.
7. Diner app (browse → chat).
8. Management app (upload/review incl. allergen confirmation → editor → order board/KOT → 86 toggle).
9. MCP server.
10. Observability wired from step 2 onward.

---

## 12. Decision log

| # | Decision |
|---|---|
| 1 | Single Python codebase; API and worker roles from one image |
| 2 | Pydantic AI for the harness; constraint extraction in plain Python + small model |
| 3 | MongoDB 8.2+ Community as the only datastore; native vector + full-text search via `mongot` |
| 4 | Hybrid retrieval with `$rankFusion` over `$vectorSearch` + `$search`, local reranker; whole items as retrieval unit |
| 5 | Single retrieval path; `diet` and `price` as index filter fields, never model-judged |
| 6 | Allergens inferred at ingestion into `allergens_inferred`, owner-reviewable, quoted not inferred at query time; staff-confirmation line mandatory |
| 7 | Photo/PDF extraction: vision model to schema with OCR attestation |
| 8 | POS exports via deterministic mapper; no LLM in mapping |
| 9 | SSE for chat streaming |
| 10 | Orders written only by Order Service; transactional; idempotent; confirmation-gated |
| 11 | MCP via FastMCP, Streamable HTTP, mounted on API; shared tool schemas |
| 12 | Tenancy via repository layer + indexed filter fields; CI lint on raw access |
| 13 | Publish gated on `index_status: indexed` to hide search lag |
| 14 | Two LLM providers; per-task models; embedding dimension pinned per index |
| 15 | Custom pytest eval harness (extraction, enrichment, chat); Langfuse for traces |
| 16 | Inline deterministic guardrails; system prompt is last line of defence |
| 17 | Stock = per-item availability flag only |
| 18 | `jobs` collection as queue; no separate broker in v1 |
| 19 | Tenant profile is structured, versioned, tenant-authored data: persona block + item-linked notes + bounded retrieval boosts; scanned on save; cannot override system rules |
| 20 | Identity is global and password-less (Google OIDC); tenant role lives in `memberships`, not on the user; four roles: `admin`, `owner`, `staff`, `user` (the default) |
| 21 | Server-side opaque sessions rather than long-lived JWTs, so a role change or revocation applies on the next request |