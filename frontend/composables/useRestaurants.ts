/**
 * The restaurants a person can switch between, and which one they are working on.
 *
 * Two sources, on purpose:
 *
 * - `/session` already carries the memberships and `active_tenant_id`, so the rail renders
 *   the right restaurant on the very first paint with no extra request and no flicker.
 * - `GET /api/v1/tenants` fills in what a membership does not know (the description, the
 *   services, whether it came from Google) and is what a create or an edit refreshes.
 *
 * The choice of restaurant lives on the server (`users.last_tenant_id`), not in this tab,
 * so it survives a reload and follows the person to their phone. It is a preference and
 * never a grant: the backend re-checks it against the memberships on every read, so being
 * removed from a restaurant silently stops it being the active one.
 */
import type { Membership, Restaurant } from '~/types/api'

/** The subset of a restaurant a membership alone can tell us about. */
export type RestaurantSummary = Pick<Restaurant, 'id' | 'name' | 'slug'> & {
  role: Membership['role'] | null
  /** The full record, once `GET /api/v1/tenants` has been through. */
  detail?: Restaurant
}

const LIST_KEY = 'mh-restaurants'
const ACTIVE_KEY = 'mh-active-restaurant'
const LOADED_KEY = 'mh-restaurants-loaded'

export function useRestaurants() {
  const { memberships, state } = useSession()
  const api = useRestaurantApi()

  /** Filled by `refresh()`; empty until then, which the memberships already cover. */
  const loaded = useState<Restaurant[]>(LIST_KEY, () => [])
  const hasLoaded = useState<boolean>(LOADED_KEY, () => false)

  /**
   * The chosen restaurant. Seeded from the session so the first render is right, then owned
   * by `select()`. `undefined` means "not decided in this tab yet" — distinct from `null`,
   * which is a considered "they have none".
   */
  const chosen = useState<string | null | undefined>(ACTIVE_KEY, () => undefined)

  const roleByTenant = computed(
    () => new Map(memberships.value.map(membership => [membership.tenant_id, membership.role])),
  )

  /**
   * Every restaurant, richest source first. An admin sees restaurants they hold no
   * membership at, so the role there is `null` rather than a guess.
   */
  const restaurants = computed<RestaurantSummary[]>(() => {
    if (hasLoaded.value) {
      return loaded.value.map(tenant => ({
        id: tenant.id,
        name: tenant.name,
        slug: tenant.slug,
        role: roleByTenant.value.get(tenant.id) ?? null,
        detail: tenant,
      }))
    }
    return memberships.value.map(membership => ({
      id: membership.tenant_id,
      name: membership.tenant_name || membership.tenant_slug,
      slug: membership.tenant_slug,
      role: membership.role,
    }))
  })

  /** The id the server would pick, before this tab has expressed a preference. */
  const serverActiveId = computed(() =>
    state.value?.authenticated ? state.value.active_tenant_id : null,
  )

  const activeId = computed<string | null>(() => {
    const preferred = chosen.value === undefined ? serverActiveId.value : chosen.value
    // Never a stale id: a restaurant that has gone from the list cannot be the active one.
    if (preferred && restaurants.value.some(item => item.id === preferred)) {
      return preferred
    }
    return restaurants.value[0]?.id ?? null
  })

  const active = computed<RestaurantSummary | null>(
    () => restaurants.value.find(item => item.id === activeId.value) ?? null,
  )

  const isPlatformAdmin = computed(
    () => state.value?.authenticated === true && state.value.user.platform_role === 'admin',
  )

  /**
   * True when the person runs the active restaurant. Only decides what the UI *offers* —
   * the backend's `assert_can_manage_tenant` is the boundary that actually holds.
   */
  const canManageActive = computed(
    () => isPlatformAdmin.value || active.value?.role === 'owner',
  )

  const hasRestaurants = computed(() => restaurants.value.length > 0)

  /**
   * Pull the full list from the backend, then the active restaurant on its own.
   *
   * Two calls, deliberately: the list omits logos so a switcher with five restaurants does
   * not download five embedded images, but the one on screen needs its mark. The second
   * call is best-effort — without it the rail falls back to the initial tile, which is not
   * worth failing a page load over.
   */
  async function refresh(): Promise<void> {
    const response = await api.list()
    loaded.value = response.tenants
    hasLoaded.value = true
    if (chosen.value === undefined) {
      chosen.value = response.active_tenant_id
    }
    const id = activeId.value
    if (id) {
      await api.get(id).then(detail => upsert(detail)).catch(() => {})
    }
  }

  /**
   * Switch restaurant, and remember it on the server so every device agrees.
   *
   * Compared against `chosen`, not `activeId`: `activeId` falls back to the first
   * restaurant in the list, so a person whose server-side choice is still unset (a fresh
   * account, or a platform admin who holds no membership) would see their first click on
   * that very restaurant treated as a no-op and never written through.
   */
  async function select(id: string): Promise<void> {
    if (id === chosen.value) {
      return
    }
    chosen.value = id
    await api.select(id)
  }

  /**
   * Fold a restaurant that was just created or edited into the list without a round trip,
   * and make it the active one when it is new.
   */
  function upsert(restaurant: Restaurant, { activate = false } = {}): void {
    const others = loaded.value.filter(item => item.id !== restaurant.id)
    // Same order the backend lists in, so a rename does not shuffle the switcher oddly.
    loaded.value = [...others, restaurant].sort((a, b) => a.name.localeCompare(b.name))
    hasLoaded.value = true
    if (activate) {
      chosen.value = restaurant.id
    }
  }

  return {
    restaurants,
    active,
    activeId,
    hasRestaurants,
    canManageActive,
    /** False until `refresh()` has been through: the difference between "none" and "not yet". */
    hasLoaded,
    refresh,
    select,
    upsert,
  }
}

/**
 * `Café Móka` -> `cafe-moka`, only to preview the handle the backend will assign.
 *
 * Must stay in step with `slugify` in `backend/app/models/tenant.py`, which is what
 * actually assigns it — a preview that disagrees with what gets stored is worse than none.
 */
export function slugify(name: string): string {
  return name
    .toLowerCase()
    .normalize('NFKD')
    .replace(/[^a-z0-9\s-]/g, '')
    .trim()
    .replace(/[\s_-]+/g, '-')
    .replace(/^-+|-+$/g, '')
}
