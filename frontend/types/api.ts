/**
 * Types mirroring the FastAPI backend contract (backend/app/schemas/*) and the
 * agent event stream (agents/core/events.py). Keep these in sync with the
 * Python models — they are the only coupling between the UI and the API.
 */

/** GET /api/health */
export interface HealthResponse {
  status: 'ok'
}

/** One entry of GET /api/agents */
export interface AgentInfo {
  name: string
  description: string
}

/** GET /api/agents */
export interface AgentListResponse {
  agents: AgentInfo[]
}

/** POST /api/agents/run and /api/agents/stream request body */
export interface AgentRequest {
  /** 1–10 000 characters */
  message: string
  /** Registered agent name; the backend defaults to "example" */
  agent?: string
}

/** POST /api/agents/run response (also the `result` of an `agent_completed` event) */
export interface AgentResponse {
  response: string
  agent: string
  metadata: Record<string, unknown>
}

/** FastAPI 422 validation error item */
export interface ValidationErrorItem {
  type: string
  loc: Array<string | number>
  msg: string
  input?: unknown
}

/** FastAPI error body: `{"detail": "..."}` or, for 422, `{"detail": [ ... ]}` */
export interface ApiErrorBody {
  detail: string | ValidationErrorItem[]
}

// ---------------------------------------------------------------------------
// Agent events — emitted by POST /api/agents/stream as SSE messages
// (`event: <type>\ndata: <JSON>\n\n`). Not consumed by the UI yet; typed here so
// a streaming chat can be added without touching the backend.
// ---------------------------------------------------------------------------

interface AgentEventBase {
  run_id: string
  agent: string
  /** ISO-8601 UTC timestamp */
  timestamp: string
}

export interface AgentStartedEvent extends AgentEventBase {
  type: 'agent_started'
  message: string
}

export interface ToolStartedEvent extends AgentEventBase {
  type: 'tool_started'
  tool: string
  input: Record<string, unknown>
}

export interface ToolCompletedEvent extends AgentEventBase {
  type: 'tool_completed'
  tool: string
  output: unknown
  duration_ms: number
}

export interface TokenEvent extends AgentEventBase {
  type: 'token'
  token: string
}

export interface AgentCompletedEvent extends AgentEventBase {
  type: 'agent_completed'
  result: AgentResponse
}

export interface AgentFailedEvent extends AgentEventBase {
  type: 'agent_failed'
  error: string
  error_type: string
}

export type AgentEvent =
  | AgentStartedEvent
  | ToolStartedEvent
  | ToolCompletedEvent
  | TokenEvent
  | AgentCompletedEvent
  | AgentFailedEvent

export type AgentEventType = AgentEvent['type']

/* Authentication — mirrors backend/app/schemas/auth.py --------------------- */

/** The strongest role a person holds, as `MeResponse.effective_role` reports it. */
export type EffectiveRole = 'admin' | 'owner' | 'staff' | 'user'

/** A person, as `GET /api/v1/auth/me` returns them. */
export interface AuthUser {
  id: string
  email: string
  name: string
  picture: string
  platform_role: 'admin' | 'user'
  is_active: boolean
  created_at: string
  last_login_at: string | null
}

/** One restaurant the signed-in person belongs to, and their role there. */
export interface Membership {
  tenant_id: string
  tenant_slug: string
  tenant_name: string
  role: 'owner' | 'staff'
}

/** GET /api/v1/auth/me */
export interface MeResponse {
  user: AuthUser
  effective_role: EffectiveRole
  /** Backend's per-role landing path (`/admin`, `/owner`, `/staff`, `/app`). */
  portal_path: string
  memberships: Membership[]
  /**
   * Which restaurant to open on: the one last switched to while the membership still
   * stands, else the first held. `null` means they belong to none — the signal that sends
   * them to onboarding.
   */
  active_tenant_id: string | null
}

/** POST /api/v1/auth/logout */
export interface LogoutResponse {
  signed_out: boolean
}

/**
 * `GET /session` — the Nitro route in `server/routes/session.get.ts`.
 *
 * A discriminated union so `if (session.authenticated)` narrows to the full profile;
 * signed out is a normal answer, not an error.
 */
export type SessionState = { authenticated: false } | ({ authenticated: true } & MeResponse)

/* Restaurants — mirrors backend/app/schemas/management.py -------------------- */

/** A role at one restaurant. `admin` is a platform role and never appears here. */
export type TenantRole = 'owner' | 'staff'

/**
 * One restaurant.
 *
 * `logo` comes back empty from every endpoint that returns more than one (a switcher must
 * not download an image per restaurant); fetch a single restaurant to get it.
 */
/** Which parts of the till a restaurant runs. Kitchen tickets have no switch. */
export interface PosSettings {
  /**
   * The till proper: floor plan, tables, takeaway bills, settling. Off, the POS is the
   * KOT board and nothing else, and the backend refuses to open an order.
   */
  billing: boolean
}

export interface Restaurant {
  id: string
  slug: string
  name: string
  description: string
  /** Google Maps link. The backend refuses anything that is not `https://`. */
  location_url: string
  /** Base64 PNG/JPEG/WEBP data URL, or `''`. */
  logo: string
  /** How the restaurant trades: `dining`, `delivery`, or anything it added. */
  services: string[]
  /** Diets catered for. Open-ended — `veg`/`non-veg` are suggestions, not a set. */
  diet_options: string[]
  /** Free-form properties: FSSAI licence, GST number, and whatever else. */
  extras: Record<string, string>
  /** Resource name of the Google Business location this was imported from, if any. */
  google_location: string | null
  pos: PosSettings
  is_active: boolean
  created_at: string
  updated_at: string | null
}

/** POST /api/v1/tenants */
export interface RestaurantCreate {
  name: string
  description?: string
  location_url?: string
  logo?: string
  services?: string[]
  diet_options?: string[]
  extras?: Record<string, string>
}

/** PATCH /api/v1/tenants/{id} — send only what changed. */
export type RestaurantUpdate = Partial<RestaurantCreate> & { is_active?: boolean, pos?: PosSettings }

/** GET /api/v1/tenants */
export interface RestaurantListResponse {
  tenants: Restaurant[]
  active_tenant_id: string | null
}

/** GET /api/v1/tenants/options — chips for the onboarding form, not a closed set. */
export interface RestaurantOptions {
  services: string[]
  diet_options: string[]
}

/** One member of a restaurant, as GET /api/v1/tenants/{id}/members returns them. */
export interface Member {
  user: AuthUser
  role: TenantRole
  created_at: string
}

/** GET /api/v1/tenants/{id}/members */
export interface MemberListResponse {
  members: Member[]
}

/** One pending invitation. Never carries the token. */
export interface Invite {
  id: string
  tenant_id: string
  email: string
  role: TenantRole
  invited_by: string
  created_at: string
  expires_at: string
  accepted_at: string | null
}

/** GET /api/v1/tenants/{id}/invites */
export interface InviteListResponse {
  invites: Invite[]
}

/** POST /api/v1/tenants/{id}/invites — the token appears here once and never again. */
export interface InviteCreatedResponse {
  invite: Invite
  token: string
  accept_url: string
}

/* Google Business Profile import — backend/app/schemas/google_business.py ---- */

/** The signed-in person's Google Business connection, or the absence of one. */
export interface GoogleConnection {
  connected: boolean
  google_email: string
  scopes: string[]
  connected_at: string | null
}

/**
 * GET /api/v1/google-business/status
 *
 * `configured` is about the deployment (the Business Profile APIs are allow-listed per
 * Google Cloud project), `connection.connected` about this person.
 */
export interface GoogleBusinessStatus {
  configured: boolean
  connection: GoogleConnection
}

/** One Google Business Profile account. */
export interface BusinessAccount {
  name: string
  account_name: string
  type: string
  verification_state: string
}

/** One Google Business location, flattened to what a restaurant profile needs. */
export interface BusinessLocation {
  name: string
  account: string
  title: string
  description: string
  address: string
  phone: string
  website: string
  maps_url: string
  place_id: string
  store_code: string
  primary_category: string
  /** True when a restaurant here was already imported from it. */
  imported: boolean
}

/** GET /api/v1/google-business/locations */
export interface BusinessLocationListResponse {
  accounts: BusinessAccount[]
  locations: BusinessLocation[]
}

/* Floor plan — backend/app/schemas/floor_plan.py ---------------------------- */

/** What an element *is*. Only a `table` can be ordered from. */
export type ElementKind = 'table' | 'wall' | 'text'

/** How an element is drawn. Purely visual; nothing downstream reads it. */
export type ElementShape = 'circle' | 'square' | 'diamond' | 'rectangle'

/**
 * One table, as identity.
 *
 * Separate from the drawing on purpose: this is what an order points at and what a QR code
 * will encode, so its `id` outlives any number of redraws. A table taken off the plan is
 * deactivated rather than deleted, and never appears in `tables` again while it is off.
 */
export interface RestaurantTable {
  id: string
  label: string
  seats: number
  is_active: boolean
  created_at: string
  updated_at: string | null
}

/** One drawn element, in canvas units with the origin at the top left. */
export interface FloorPlanElement {
  id: string
  kind: ElementKind
  shape: ElementShape
  /** The join back to `RestaurantTable`; set on, and only on, a table element. */
  table_id: string | null
  text: string
  x: number
  y: number
  width: number
  height: number
  rotation: number
}

/** GET and PUT /api/v1/tenants/{id}/floor-plan */
export interface FloorPlan {
  width: number
  height: number
  elements: FloorPlanElement[]
  tables: RestaurantTable[]
  updated_at: string | null
}

/** One element as submitted: a new table carries its name, not an id the server assigns. */
export interface FloorPlanElementSave {
  id: string
  kind: ElementKind
  shape: ElementShape
  table_id?: string
  label?: string
  seats?: number
  text?: string
  x: number
  y: number
  width: number
  height: number
  rotation: number
}

/** PUT /api/v1/tenants/{id}/floor-plan — the whole plan, never one element. */
export interface FloorPlanSave {
  width: number
  height: number
  elements: FloorPlanElementSave[]
}

/* Menu categories — backend/app/schemas/category.py ------------------------- */

/** Whether a section is on the menu a diner reads. */
export type CategoryStatus = 'active' | 'hidden'

/**
 * One section of a menu.
 *
 * `rank` is the running order, lower first; the backend breaks a tie on the name so the
 * list is stable rather than arbitrary.
 */
export interface Category {
  id: string
  name: string
  rank: number
  status: CategoryStatus
  created_at: string
  updated_at: string | null
}

/** GET /api/v1/tenants/{id}/categories — includes hidden ones; this is the owner's list. */
export interface CategoryListResponse {
  categories: Category[]
}

/** POST /api/v1/tenants/{id}/categories — omit `rank` to land at the bottom. */
export interface CategoryCreate {
  name: string
  rank?: number
  status?: CategoryStatus
}

/** PATCH /api/v1/tenants/{id}/categories/{categoryId} — only what is present changes. */
export interface CategoryUpdate {
  name?: string
  rank?: number
  status?: CategoryStatus
}

/* Menu items and the POS import — backend/app/schemas/menu.py ---------------- */

/** One form a dish is sold in, carrying its own price. */
export interface MenuVariation {
  group: string
  name: string
  price: number
  sap_code: string
  packing_charges: number
}

/** A set of extras offered with a dish; the items in it live in the add-ons export. */
export interface MenuAddonGroup {
  name: string
  selection: string
  minimum: number
  maximum: number
}

/**
 * One dish.
 *
 * `price_from` is what a menu prints: the item's own price, or the cheapest variation for a
 * dish that is priced by its variations (those carry `price` 0 on purpose).
 */
export interface MenuItem {
  id: string
  name: string
  online_name: string
  description: string
  category: string
  parent_category: string
  short_code: string
  short_code_2: string
  sap_code: string
  hsn_code: string
  diet: string
  price: number
  price_from: number
  /** "Container charges", in the POS's words. */
  packing_charges: number
  profit_margin: number
  weight: number
  weight_unit: string
  gst_type: GstType | null
  order_types: string[]
  expose_in: string[]
  allow_decimal_quantity: boolean
  manufactured_on: string | null
  expires_on: string | null
  rank: number
  /** Where the picture is served from — a URL, never the bytes. Empty when there is none. */
  image_url: string
  is_available: boolean
  variations: MenuVariation[]
  addon_group: MenuAddonGroup | null
  created_at: string
  updated_at: string | null
}

/** How a dish is taxed. A restaurant meal is a service; a packaged item is goods. */
export type GstType = 'services' | 'goods'

/**
 * The editable half of a dish — everything the item form collects.
 *
 * `null` is a real instruction here, not an omission: clearing an expiry date or an add-on
 * group has to be expressible, which is why the API excludes unset fields but not null ones.
 */
export interface MenuItemWrite {
  name?: string
  online_name?: string
  description?: string
  category?: string
  parent_category?: string
  short_code?: string
  short_code_2?: string
  sap_code?: string
  hsn_code?: string
  diet?: string
  price?: number
  packing_charges?: number
  profit_margin?: number
  weight?: number
  weight_unit?: string
  gst_type?: GstType | null
  order_types?: string[]
  expose_in?: string[]
  allow_decimal_quantity?: boolean
  manufactured_on?: string | null
  expires_on?: string | null
  rank?: number
  image_url?: string
  is_available?: boolean
}

/**
 * GET /api/v1/tenants/{id}/menu/options — what the item form offers.
 *
 * Served rather than hard-coded in the UI so the form and the backend validators cannot
 * drift: every list here is the one the document model checks against.
 */
export interface MenuOptions {
  diets: string[]
  order_types: string[]
  exposures: string[]
  weight_units: string[]
  gst_types: GstType[]
}

/**
 * POST /api/v1/tenants/{id}/menu/availability
 *
 * Either a list of dishes or a whole section — the two ways a floor manager thinks about it:
 * this dish has run out, or the grill is off tonight.
 */
export interface AvailabilityUpdate {
  item_ids?: string[]
  category?: string
  on: boolean
}

/** How many dishes changed. Zero is normal — they were already like that. */
export interface AvailabilityResponse {
  changed: number
}

/** POST /api/v1/tenants/{id}/menu/images — a URL, because a URL is all an item stores. */
export interface MenuImageUpload {
  url: string
  content_type: string
  size: number
}

/** GET /api/v1/tenants/{id}/menu/items */
export interface MenuItemListResponse {
  items: MenuItem[]
  total: number
}

/** One row of an import, as it would be stored. */
export interface ImportPreviewItem {
  name: string
  category: string
  diet: string
  price: number
  variations: number
}

/**
 * POST /api/v1/tenants/{id}/menu/import
 *
 * The same shape answers the dry run and the commit; `committed` is what tells them apart,
 * and it is the field to read before saying anything reassuring.
 */
export interface MenuImportResponse {
  committed: boolean
  item_count: number
  skipped: number
  warnings: string[]
  new_categories: string[]
  existing_categories: string[]
  items_replaced: number
  items_written: number
  /** Rows carrying a picture, inline as base64 or as a link. */
  images: number
  sample: ImportPreviewItem[]
}

/* Orders and kitchen tickets — backend/app/schemas/order.py ------------------ */

export type OrderKind = 'dine-in' | 'takeaway'

/**
 * `open` while the table is still ordering; `billed` once the bill is on the table and
 * nothing more may be added; `closed` when the counter has been paid; `cancelled` if it
 * never got that far.
 */
export type OrderStatus = 'open' | 'billed' | 'closed' | 'cancelled'

export interface OrderLineVariation {
  name: string
  price: number
}

/**
 * One dish on the ticket, at the price it was ordered at.
 *
 * `kot_id` is set once the line has gone to the kitchen and never changes after. Quantity
 * and note are editable only while it is null.
 */
export interface OrderLine {
  id: string
  item_id: string
  name: string
  variation: OrderLineVariation | null
  quantity: number
  unit_price: number
  total: number
  note: string
  kot_id: string | null
  added_at: string
}

/** One visit's worth of food. Totals are the server's, so no client adds them up differently. */
export interface Order {
  id: string
  number: number
  kind: OrderKind
  status: OrderStatus
  table_id: string | null
  table_label: string
  lines: OrderLine[]
  kot_ids: string[]
  pending_count: number
  subtotal: number
  total: number
  opened_at: string
  billed_at: string | null
  closed_at: string | null
  cancelled_at: string | null
}

export interface OrderListResponse {
  orders: Order[]
}

/** POST /api/v1/tenants/{id}/orders — a table seats; no table starts a takeaway bill. */
export interface OrderOpen {
  table_id?: string
  idempotency_key?: string
}

/** One dish to add. `variation` names the form when the dish comes in several. */
export interface OrderLineIn {
  id: string
  item_id: string
  variation?: string
  quantity?: number
  note?: string
}

export interface KotLine {
  line_id: string
  name: string
  variation: string
  quantity: number
  note: string
}

/** Where a ticket came from: a captain at the till, or (once live) the table's own QR menu. */
export type KotSource = 'pos' | 'diner'

/** A kitchen ticket: the lines sent to the pass in one go. */
export interface Kot {
  id: string
  number: number
  order_id: string
  order_number: number
  kind: OrderKind
  table_label: string
  lines: KotLine[]
  source: KotSource
  /** Snapshot of who sent it, as the board says it. */
  sent_by_name: string
  sent_at: string
  /** The kitchen's "seen". Set once, never cleared. */
  acknowledged_at: string | null
}

export interface KotListResponse {
  kots: Kot[]
}

/* ---------------------------------------------------------------- the diner's side */

/** GET /api/v1/public/restaurants/{id}/menu — what a phone at a table sees. No session. */
export interface PublicRestaurant {
  name: string
  description: string
  logo: string
}

export interface PublicTable {
  id: string
  label: string
}

export interface PublicVariation {
  name: string
  price: number
}

/** A dish as the table sees it: no codes, costs or stock dates. */
export interface PublicItem {
  id: string
  name: string
  description: string
  diet: string
  price: number
  price_from: number
  image_url: string
  variations: PublicVariation[]
}

export interface PublicSection {
  name: string
  items: PublicItem[]
}

export interface PublicMenuResponse {
  restaurant: PublicRestaurant
  /** The table the QR code was on; null when the link names none, or it is gone. */
  table: PublicTable | null
  sections: PublicSection[]
}

export interface PublicLineIn {
  item_id: string
  variation?: string | null
  quantity: number
  note?: string
}

/** POST /api/v1/public/restaurants/{id}/orders */
export interface PublicOrderIn {
  table_id: string
  lines: PublicLineIn[]
}

export interface PublicOrderOut {
  order_number: number
  kot_number: number
  table_label: string
}
