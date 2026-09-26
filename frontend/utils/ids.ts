/**
 * A client-generated id for something the server has not seen yet.
 *
 * Order lines and floor-plan elements both need to be addressable - selected, edited,
 * removed - before a round trip, so their ids are minted here. `randomUUID` needs a secure
 * context; the fallback keeps a plain-HTTP dev server working.
 */
export function newId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  return `id-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
}
