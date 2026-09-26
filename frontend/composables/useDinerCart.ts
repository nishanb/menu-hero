/**
 * What the table is about to order, kept on the phone until it is sent.
 *
 * Per restaurant and table, in localStorage: a diner who locks the phone, gets a call and
 * comes back should find the cart where they left it. A line is a dish in one form - the
 * same dish as "Egg Drop" and as "Egg Boiled" is two lines, because it is two prices and
 * two things for the kitchen.
 */
import { useLocalStorage } from '@vueuse/core'
import type { PublicItem, PublicVariation } from '~/types/api'

export interface CartLine {
  key: string
  item_id: string
  name: string
  variation: string | null
  unit_price: number
  quantity: number
  note: string
}

const MAX_QUANTITY = 20

export function useDinerCart(restaurantId: string, tableId: string | null) {
  const lines = useLocalStorage<CartLine[]>(`mh-cart:${restaurantId}:${tableId ?? 'none'}`, [])

  const count = computed(() => lines.value.reduce((n, line) => n + line.quantity, 0))
  const total = computed(() => lines.value.reduce((n, line) => n + line.unit_price * line.quantity, 0))

  function keyFor(item: PublicItem, variation: PublicVariation | null): string {
    return variation ? `${item.id}:${variation.name}` : item.id
  }

  /** How many of this dish, in every form, are in the cart - what the menu row shows. */
  function quantityOf(item: PublicItem): number {
    return lines.value
      .filter(line => line.item_id === item.id)
      .reduce((n, line) => n + line.quantity, 0)
  }

  function add(item: PublicItem, variation: PublicVariation | null): void {
    const key = keyFor(item, variation)
    const existing = lines.value.find(line => line.key === key)
    if (existing) {
      existing.quantity = Math.min(MAX_QUANTITY, existing.quantity + 1)
      return
    }
    lines.value.push({
      key,
      item_id: item.id,
      name: item.name,
      variation: variation?.name ?? null,
      unit_price: variation ? variation.price : item.price,
      quantity: 1,
      note: '',
    })
  }

  function setQuantity(key: string, quantity: number): void {
    const line = lines.value.find(entry => entry.key === key)
    if (!line) {
      return
    }
    if (quantity <= 0) {
      lines.value = lines.value.filter(entry => entry.key !== key)
      return
    }
    line.quantity = Math.min(MAX_QUANTITY, quantity)
  }

  function setNote(key: string, note: string): void {
    const line = lines.value.find(entry => entry.key === key)
    if (line) {
      line.note = note.slice(0, 120)
    }
  }

  function clear(): void {
    lines.value = []
  }

  return { lines, count, total, quantityOf, add, setQuantity, setNote, clear }
}
