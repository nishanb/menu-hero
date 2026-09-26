/**
 * The POS print pipeline, shared by every screen that has something to print.
 *
 * One job at a time: the caller hands over a ticket or a bill, it is rendered into the
 * `<PosPrintSheets>` area (display:none on screen, the only visible thing in print), the
 * page prints, and `afterprint` clears the area. `window.print()` is synchronous in every
 * browser that matters, so a caller can `await print(...)` and act once the paper is out.
 */
import type { Kot, Order } from '~/types/api'

export type PrintJob = { kind: 'kot', kot: Kot } | { kind: 'bill', order: Order }

export function usePosPrinter() {
  const job = ref<PrintJob | null>(null)

  useHead({
    style: [{ innerHTML: '@page { size: 80mm auto; margin: 4mm; }' }],
  })

  async function print(next: PrintJob): Promise<void> {
    job.value = next
    await nextTick()
    window.print()
  }

  function clear(): void {
    job.value = null
  }

  onMounted(() => window.addEventListener('afterprint', clear))
  onBeforeUnmount(() => window.removeEventListener('afterprint', clear))

  return { job, print }
}
