<script setup lang="ts">
/**
 * A kitchen order ticket, as it comes off the printer at the pass.
 *
 * Big type, no prices, nothing decorative: the kitchen reads this at arm's length under
 * heat lamps, and the only things that matter are where it is going, what, how many, and
 * anything the table said. 80mm wide because that is what a thermal printer is.
 */
import type { Kot } from '~/types/api'

defineProps<{ kot: Kot, restaurant: string }>()

const time = new Intl.DateTimeFormat('en-GB', { hour: '2-digit', minute: '2-digit' })
</script>

<template>
  <article class="w-[72mm] bg-white px-[3mm] py-[4mm] font-mono text-[11pt] leading-tight text-black">
    <header class="border-b-2 border-dashed border-black pb-2 text-center">
      <p class="text-[9pt] tracking-[0.2em] uppercase">{{ restaurant }}</p>
      <p class="mt-1 text-[22pt] leading-none font-bold">KOT {{ kot.number }}</p>
      <p class="mt-1.5 text-[16pt] font-bold">
        {{ kot.kind === 'takeaway' ? 'TAKEAWAY' : `TABLE ${kot.table_label}` }}
      </p>
      <p class="text-[9pt]">Order #{{ kot.order_number }} · {{ time.format(new Date(kot.sent_at)) }}</p>
      <p class="text-[9pt]">{{ kot.source === 'diner' ? 'From the table (QR)' : kot.sent_by_name }}</p>
    </header>

    <ul class="mt-2 grid gap-1.5">
      <li v-for="line in kot.lines" :key="line.line_id" class="flex gap-2">
        <span class="w-8 shrink-0 text-[15pt] font-bold tabular-nums">{{ line.quantity }}×</span>
        <span class="min-w-0 flex-1">
          <span class="block text-[13pt] font-bold uppercase">{{ line.name }}</span>
          <span v-if="line.variation" class="block text-[10pt]">— {{ line.variation }}</span>
          <span v-if="line.note" class="block text-[10pt] font-bold">** {{ line.note }} **</span>
        </span>
      </li>
    </ul>

    <footer class="mt-3 border-t-2 border-dashed border-black pt-1.5 text-center text-[9pt]">
      {{ kot.lines.reduce((n, line) => n + line.quantity, 0) }} items
    </footer>
  </article>
</template>
