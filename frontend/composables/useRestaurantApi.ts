/**
 * Typed calls to the restaurant, team, invitation and Google Business endpoints.
 *
 * One function per backend route, in the same shape as `useApi.ts` — that file stays with
 * the health and agent endpoints so neither grows into a grab bag. Every function rejects
 * with an `ApiError`, because they all go through the `$api` plugin.
 */
import type {
  AvailabilityResponse,
  AvailabilityUpdate,
  BusinessLocationListResponse,
  Category,
  CategoryCreate,
  CategoryListResponse,
  CategoryUpdate,
  FloorPlan,
  FloorPlanSave,
  Kot,
  KotListResponse,
  MenuImageUpload,
  MenuImportResponse,
  MenuItem,
  MenuItemListResponse,
  MenuItemWrite,
  MenuOptions,
  Order,
  OrderLineIn,
  OrderListResponse,
  OrderOpen,
  GoogleBusinessStatus,
  Invite,
  InviteCreatedResponse,
  InviteListResponse,
  Member,
  MemberListResponse,
  Restaurant,
  RestaurantCreate,
  RestaurantListResponse,
  RestaurantOptions,
  RestaurantUpdate,
  TenantRole,
} from '~/types/api'

export function useRestaurantApi() {
  const { $api } = useNuxtApp()

  return {
    /** GET /api/v1/tenants — the caller's restaurants, without logos. */
    list: (): Promise<RestaurantListResponse> => $api<RestaurantListResponse>('/v1/tenants'),

    /** GET /api/v1/tenants/options — suggested services and diet options. */
    options: (): Promise<RestaurantOptions> => $api<RestaurantOptions>('/v1/tenants/options'),

    /** GET /api/v1/tenants/{id} — one restaurant, logo included. */
    get: (id: string): Promise<Restaurant> => $api<Restaurant>(`/v1/tenants/${id}`),

    /** POST /api/v1/tenants — the caller becomes its owner. */
    create: (body: RestaurantCreate): Promise<Restaurant> =>
      $api<Restaurant>('/v1/tenants', { method: 'POST', body }),

    /** PATCH /api/v1/tenants/{id} — only the fields present change. */
    update: (id: string, body: RestaurantUpdate): Promise<Restaurant> =>
      $api<Restaurant>(`/v1/tenants/${id}`, { method: 'PATCH', body }),

    /** PUT /api/v1/tenants/{id}/current — remember this one across devices. */
    select: (id: string): Promise<Restaurant> =>
      $api<Restaurant>(`/v1/tenants/${id}/current`, { method: 'PUT' }),

    /** GET /api/v1/tenants/{id}/floor-plan — the plan and its tables, in one round trip. */
    floorPlan: (id: string): Promise<FloorPlan> =>
      $api<FloorPlan>(`/v1/tenants/${id}/floor-plan`),

    /** PUT /api/v1/tenants/{id}/floor-plan — the whole plan; tables are reconciled server-side. */
    saveFloorPlan: (id: string, body: FloorPlanSave): Promise<FloorPlan> =>
      $api<FloorPlan>(`/v1/tenants/${id}/floor-plan`, { method: 'PUT', body }),

    /** GET /api/v1/tenants/{id}/categories — in reading order, hidden ones included. */
    categories: (id: string): Promise<CategoryListResponse> =>
      $api<CategoryListResponse>(`/v1/tenants/${id}/categories`),

    /** POST /api/v1/tenants/{id}/categories — no rank means "put it at the bottom". */
    createCategory: (id: string, body: CategoryCreate): Promise<Category> =>
      $api<Category>(`/v1/tenants/${id}/categories`, { method: 'POST', body }),

    /** PATCH /api/v1/tenants/{id}/categories/{categoryId} */
    updateCategory: (id: string, categoryId: string, body: CategoryUpdate): Promise<Category> =>
      $api<Category>(`/v1/tenants/${id}/categories/${categoryId}`, { method: 'PATCH', body }),

    /** DELETE /api/v1/tenants/{id}/categories/{categoryId} */
    deleteCategory: (id: string, categoryId: string): Promise<void> =>
      $api<void>(`/v1/tenants/${id}/categories/${categoryId}`, { method: 'DELETE' }),

    /** GET /api/v1/tenants/{id}/menu/items — grouped by section, ranked within it. */
    menuItems: (id: string): Promise<MenuItemListResponse> =>
      $api<MenuItemListResponse>(`/v1/tenants/${id}/menu/items`),

    /** GET /api/v1/tenants/{id}/menu/options — what the item form offers. */
    menuOptions: (id: string): Promise<MenuOptions> =>
      $api<MenuOptions>(`/v1/tenants/${id}/menu/options`),

    /** POST /api/v1/tenants/{id}/menu/items */
    createItem: (id: string, body: MenuItemWrite): Promise<MenuItem> =>
      $api<MenuItem>(`/v1/tenants/${id}/menu/items`, { method: 'POST', body }),

    /** PATCH /api/v1/tenants/{id}/menu/items/{itemId} — only what is present changes. */
    updateItem: (id: string, itemId: string, body: MenuItemWrite): Promise<MenuItem> =>
      $api<MenuItem>(`/v1/tenants/${id}/menu/items/${itemId}`, { method: 'PATCH', body }),

    /**
     * POST /api/v1/tenants/{id}/menu/availability — turn dishes on or off.
     *
     * A service decision, not a menu edit: nothing is published and no version changes. One
     * call for a whole section, because a section of a real menu runs to 28 dishes.
     */
    setAvailability: (id: string, body: AvailabilityUpdate): Promise<AvailabilityResponse> =>
      $api<AvailabilityResponse>(`/v1/tenants/${id}/menu/availability`, {
        method: 'POST',
        body,
      }),

    /**
     * POST /api/v1/tenants/{id}/menu/images — store a picture, get back the URL for an item.
     *
     * Its own call rather than base64 inside the item body: a 2 MB image in a JSON patch is
     * 2 MB re-sent every time the price changes. `FormData` again, so no `Content-Type` here.
     */
    uploadMenuImage: (id: string, file: File): Promise<MenuImageUpload> => {
      const body = new FormData()
      body.append('file', file)
      return $api<MenuImageUpload>(`/v1/tenants/${id}/menu/images`, { method: 'POST', body })
    },

    /** DELETE /api/v1/tenants/{id}/menu/items/{itemId} */
    deleteItem: (id: string, itemId: string): Promise<void> =>
      $api<void>(`/v1/tenants/${id}/menu/items/${itemId}`, { method: 'DELETE' }),

    /**
     * POST /api/v1/tenants/{id}/menu/import
     *
     * `dryRun` reads the file and reports without writing — do that first, always. The body
     * is `FormData`, so no `Content-Type` is set here: the browser has to add the multipart
     * boundary itself, and naming the type by hand is what breaks that.
     */
    importMenu: (id: string, file: File, dryRun: boolean): Promise<MenuImportResponse> => {
      const body = new FormData()
      body.append('file', file)
      return $api<MenuImportResponse>(`/v1/tenants/${id}/menu/import`, {
        method: 'POST',
        query: { dry_run: dryRun },
        body,
      })
    },

    /* ---- the POS. Every order mutation goes through the backend's single writer. ---- */

    /** GET /api/v1/tenants/{id}/orders — 'active' (open + billed) or 'recent' (everything). */
    orders: (id: string, scope: 'active' | 'recent' = 'active'): Promise<OrderListResponse> =>
      $api<OrderListResponse>(`/v1/tenants/${id}/orders`, { query: { scope } }),

    /** POST /api/v1/tenants/{id}/orders — seat a table (idempotent) or start a takeaway. */
    openOrder: (id: string, body: OrderOpen): Promise<Order> =>
      $api<Order>(`/v1/tenants/${id}/orders`, { method: 'POST', body }),

    /** GET /api/v1/tenants/{id}/orders/{orderId} */
    order: (id: string, orderId: string): Promise<Order> =>
      $api<Order>(`/v1/tenants/${id}/orders/${orderId}`),

    /** POST .../orders/{orderId}/lines — prices are frozen at this moment. */
    addLines: (id: string, orderId: string, lines: OrderLineIn[]): Promise<Order> =>
      $api<Order>(`/v1/tenants/${id}/orders/${orderId}/lines`, { method: 'POST', body: { lines } }),

    /** PATCH .../orders/{orderId}/lines/{lineId} — only while the kitchen has not seen it. */
    updateLine: (
      id: string,
      orderId: string,
      lineId: string,
      body: { quantity?: number, note?: string },
    ): Promise<Order> =>
      $api<Order>(`/v1/tenants/${id}/orders/${orderId}/lines/${lineId}`, {
        method: 'PATCH',
        body,
      }),

    /** DELETE .../orders/{orderId}/lines/{lineId} — only while the kitchen has not seen it. */
    removeLine: (id: string, orderId: string, lineId: string): Promise<Order> =>
      $api<Order>(`/v1/tenants/${id}/orders/${orderId}/lines/${lineId}`, { method: 'DELETE' }),

    /** POST .../orders/{orderId}/kot — one ticket for everything not yet sent. */
    sendKot: (id: string, orderId: string): Promise<Kot> =>
      $api<Kot>(`/v1/tenants/${id}/orders/${orderId}/kot`, { method: 'POST' }),

    /** GET .../orders/{orderId}/kots */
    kots: (id: string, orderId: string): Promise<KotListResponse> =>
      $api<KotListResponse>(`/v1/tenants/${id}/orders/${orderId}/kots`),

    /** GET /api/v1/tenants/{id}/kots — every ticket of every order still on the floor. */
    activeKots: (id: string): Promise<KotListResponse> =>
      $api<KotListResponse>(`/v1/tenants/${id}/kots`),

    /** POST /api/v1/tenants/{id}/kots/{kotId}/acknowledge — the kitchen has seen it; idempotent. */
    acknowledgeKot: (id: string, kotId: string): Promise<Kot> =>
      $api<Kot>(`/v1/tenants/${id}/kots/${kotId}/acknowledge`, { method: 'POST' }),

    /** POST .../orders/{orderId}/bill — refused while lines are pending. */
    billOrder: (id: string, orderId: string): Promise<Order> =>
      $api<Order>(`/v1/tenants/${id}/orders/${orderId}/bill`, { method: 'POST' }),

    /** POST .../orders/{orderId}/close — paid at the counter; the table is free. */
    closeOrder: (id: string, orderId: string): Promise<Order> =>
      $api<Order>(`/v1/tenants/${id}/orders/${orderId}/close`, { method: 'POST' }),

    /** POST .../orders/{orderId}/cancel — allowed until it is paid. */
    cancelOrder: (id: string, orderId: string): Promise<Order> =>
      $api<Order>(`/v1/tenants/${id}/orders/${orderId}/cancel`, { method: 'POST' }),

    /** GET /api/v1/tenants/{id}/members */
    members: (id: string): Promise<MemberListResponse> =>
      $api<MemberListResponse>(`/v1/tenants/${id}/members`),

    /** PATCH /api/v1/tenants/{id}/members/{userId} */
    changeRole: (id: string, userId: string, role: TenantRole): Promise<Member> =>
      $api<Member>(`/v1/tenants/${id}/members/${userId}`, { method: 'PATCH', body: { role } }),

    /** DELETE /api/v1/tenants/{id}/members/{userId} */
    removeMember: (id: string, userId: string): Promise<void> =>
      $api<void>(`/v1/tenants/${id}/members/${userId}`, { method: 'DELETE' }),

    /** GET /api/v1/tenants/{id}/invites — pending only. */
    invites: (id: string): Promise<InviteListResponse> =>
      $api<InviteListResponse>(`/v1/tenants/${id}/invites`),

    /** POST /api/v1/tenants/{id}/invites — the token comes back once, here. */
    invite: (id: string, email: string, role: TenantRole): Promise<InviteCreatedResponse> =>
      $api<InviteCreatedResponse>(`/v1/tenants/${id}/invites`, {
        method: 'POST',
        body: { email, role },
      }),

    /** DELETE /api/v1/tenants/{id}/invites/{inviteId} — the link stops working at once. */
    revokeInvite: (id: string, inviteId: string): Promise<void> =>
      $api<void>(`/v1/tenants/${id}/invites/${inviteId}`, { method: 'DELETE' }),

    /** POST /api/v1/auth/invites/accept — for someone already signed in. */
    acceptInvite: (token: string): Promise<Invite> =>
      $api<Invite>('/v1/auth/invites/accept', { method: 'POST', body: { token } }),
  }
}

/**
 * The Google Business Profile import.
 *
 * `connect` is deliberately not here: it answers 307 to accounts.google.com, so it has to
 * be a real browser navigation rather than a fetch that would die on CORS. Use
 * `googleBusinessConnectUrl()` with `window.location.href`, exactly as the login page does.
 */
export function useGoogleBusinessApi() {
  const { $api } = useNuxtApp()

  return {
    /** GET /api/v1/google-business/status — answers without calling Google. */
    status: (): Promise<GoogleBusinessStatus> =>
      $api<GoogleBusinessStatus>('/v1/google-business/status'),

    /** GET /api/v1/google-business/locations — the businesses the account administers. */
    locations: (): Promise<BusinessLocationListResponse> =>
      $api<BusinessLocationListResponse>('/v1/google-business/locations'),

    /** POST /api/v1/google-business/import — one location, as a restaurant the caller owns. */
    import: (location: string): Promise<Restaurant> =>
      $api<Restaurant>('/v1/google-business/import', { method: 'POST', body: { location } }),

    /** POST /api/v1/google-business/sync — refresh an imported restaurant from Google. */
    sync: (tenantId: string): Promise<Restaurant> =>
      $api<Restaurant>('/v1/google-business/sync', {
        method: 'POST',
        body: { tenant_id: tenantId },
      }),

    /** DELETE /api/v1/google-business/connection — revoke at Google and forget it here. */
    disconnect: (): Promise<void> =>
      $api<void>('/v1/google-business/connection', { method: 'DELETE' }),
  }
}

/** Where to send the browser to start the Business Profile consent round trip. */
export function googleBusinessConnectUrl(next: string): string {
  return `/api/v1/google-business/connect?next=${encodeURIComponent(next)}`
}
