<script setup lang="ts">
/**
 * The bill, as it goes on the table: what was ordered, at the price it was ordered at.
 *
 * Every number here is the server's - the lines snapshot the menu at the moment they were
 * added and the totals come back from the API - so this component adds nothing up. 80mm
 * wide for a thermal printer; "Save as PDF" gives a narrow receipt, which is correct.
 */
import type { Order, Restaurant } from '~/types/api'

defineProps<{ order: Order, restaurant: Restaurant | undefined, name: string }>()

const money = new Intl.NumberFormat('en-IN', { minimumFractionDigits: 2 })
const when = new Intl.DateTimeFormat('en-GB', {
  day: '2-digit',
  month: 'short',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
})
</script>

<template>
  <article class="w-[72mm] bg-white px-[3mm] py-[4mm] font-mono text-[10pt] leading-tight text-black">
    <header class="border-b border-dashed border-black pb-2 text-center">
      <p class="text-[13pt] font-bold uppercase">{{ name }}</p>
      <p v-if="restaurant?.description" class="mt-0.5 text-[8pt]">{{ restaurant.description }}</p>
      <p v-if="restaurant?.extras?.gst_number" class="mt-0.5 text-[8pt]">
        GSTIN {{ restaurant.extras.gst_number }}
      </p>
    </header>

    <dl class="mt-2 grid grid-cols-2 gap-x-2 text-[9pt]">
      <dt>Bill</dt>
      <dd class="text-right">#{{ order.number }}</dd>
      <dt>{{ order.kind === 'takeaway' ? 'Takeaway' : 'Table' }}</dt>
      <dd class="text-right">{{ order.kind === 'takeaway' ? '—' : order.table_label }}</dd>
      <dt>Date</dt>
      <dd class="text-right">{{ when.format(new Date(order.billed_at ?? order.opened_at)) }}</dd>
    </dl>

    <table class="mt-2 w-full border-t border-b border-dashed border-black text-[9pt]">
      <thead>
        <tr class="text-left">
          <th class="py-1 font-normal">Item</th>
          <th class="py-1 text-right font-normal">Qty</th>
          <th class="py-1 text-right font-normal">Amount</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="line in order.lines" :key="line.id" class="align-top">
          <td class="py-0.5 pr-1">
            {{ line.name }}
            <span v-if="line.variation" class="block text-[8pt]">{{ line.variation.name }}</span>
          </td>
          <td class="py-0.5 text-right tabular-nums">{{ line.quantity }}</td>
          <td class="py-0.5 text-right tabular-nums">{{ money.format(line.total) }}</td>
        </tr>
      </tbody>
    </table>

    <dl class="mt-2 grid grid-cols-2 gap-x-2 text-[10pt]">
      <dt>Subtotal</dt>
      <dd class="text-right tabular-nums">{{ money.format(order.subtotal) }}</dd>
      <dt class="mt-1 text-[13pt] font-bold">Total</dt>
      <dd class="mt-1 text-right text-[13pt] font-bold tabular-nums">{{ money.format(order.total) }}</dd>
    </dl>

    <footer class="mt-3 border-t border-dashed border-black pt-2 text-center text-[8pt]">
      <p>Pay at the counter · Thank you</p>
      <p v-if="restaurant?.extras?.fssai_licence" class="mt-0.5">
        FSSAI {{ restaurant.extras.fssai_licence }}
      </p>
    </footer>
  </article>
</template>
