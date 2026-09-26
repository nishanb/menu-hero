/**
 * The diner's two calls, with no session behind them.
 *
 * Kept apart from `useRestaurantApi` on purpose: that one is the management surface and
 * every call in it assumes a member. These are what a phone at a table can do.
 */
import type { PublicMenuResponse, PublicOrderIn, PublicOrderOut } from '~/types/api'

export function useDinerApi() {
  const { $api } = useNuxtApp()

  return {
    /** GET /api/v1/public/restaurants/{id}/menu?table= — available dishes, by section. */
    menu: (id: string, table: string | null): Promise<PublicMenuResponse> =>
      $api<PublicMenuResponse>(`/v1/public/restaurants/${id}/menu`, {
        query: table ? { table } : {},
      }),

    /** POST /api/v1/public/restaurants/{id}/orders — straight to the kitchen. */
    order: (id: string, body: PublicOrderIn): Promise<PublicOrderOut> =>
      $api<PublicOrderOut>(`/v1/public/restaurants/${id}/orders`, { method: 'POST', body }),
  }
}
