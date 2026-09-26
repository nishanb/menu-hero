/**
 * The two things every POS screen writes: money, and how long ago.
 *
 * One place, so the floor and the ticket never disagree on a rupee format, and so "12m"
 * means the same twelve minutes on both.
 */

/** Two decimals: the ticket, the bill, the running total. */
export const money = new Intl.NumberFormat('en-IN', { minimumFractionDigits: 2 })

/** Whole rupees: menu tiles, where the decimals are noise. */
export const price = new Intl.NumberFormat('en-IN', { minimumFractionDigits: 0 })

/** `12m` / `1h 05m` — how long a table has been sitting, which is what a floor manager scans for. */
export function since(iso: string): string {
  const minutes = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000))
  if (minutes < 60) {
    return `${minutes}m`
  }
  return `${Math.floor(minutes / 60)}h ${String(minutes % 60).padStart(2, '0')}m`
}
