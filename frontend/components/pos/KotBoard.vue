<script setup lang="ts">
/**
 * The kitchen's section of the till: the queue of tickets nobody has seen yet, oldest on top.
 *
 * Two things can be done to a ticket here, and only two - acknowledge it and print it.
 * Acknowledging is the kitchen saying "seen": the button turns to **Acked** so the tap has
 * shown for itself, and the ticket leaves the queue - here and on every other till - at the
 * next poll, not to come back (the order's own history keeps it).
 * Printing is for the terminal by the pass that has no printer of its own, or a ticket that
 * jammed.
 *
 * Tickets come from a captain at the till or from the table itself through the QR menu.
 * The board reads the same either way; the footer says which, so the kitchen knows who to
 * shout at.
 */
import type { Kot } from '~/types/api'
import { toApiError } from '~/utils/api-error'
import { since } from '~/utils/pos'

const props = defineProps<{ tenantId: string, kots: Kot[] }>()

const emit = defineEmits<{
  /** The kitchen has seen it; the owner of the list takes it out. */
  acknowledged: [kot: Kot]
  print: [kot: Kot]
}>()

const api = useRestaurantApi()
const router = useRouter()

const busy = ref('')
const error = ref('')

/** Oldest on top - the one the kitchen is latest on. */
const ordered = computed(() => [...props.kots].sort((a, b) => a.sent_at.localeCompare(b.sent_at)))

function origin(kot: Kot): string {
  return kot.source === 'diner' ? 'From the table · QR' : `Captain · ${kot.sent_by_name || '—'}`
}

async function acknowledge(kot: Kot): Promise<void> {
  busy.value = kot.id
  error.value = ''
  try {
    emit('acknowledged', await api.acknowledgeKot(props.tenantId, kot.id))
  }
  catch (cause) {
    error.value = toApiError(cause).detail
  }
  finally {
    busy.value = ''
  }
}
</script>

<template>
  <section class="flex min-h-0 flex-1 flex-col rounded-xl border border-border bg-card">
    <Alert v-if="error" variant="destructive" class="m-3">
      <AlertDescription>{{ error }}</AlertDescription>
    </Alert>

    <p v-if="!kots.length" class="grid flex-1 place-items-center px-4 py-10 text-center text-sm text-muted-foreground">
      All caught up. Tickets show up here the moment they are sent — from the till, or from
      a table's QR menu — and leave when the kitchen acknowledges them.
    </p>

    <!-- Oldest first, tiles that read from the pass: auto-fill so a wide terminal shows a
         row of five and a tablet two. -->
    <div v-else class="grid min-h-0 flex-1 content-start gap-3 overflow-y-auto p-3 [grid-template-columns:repeat(auto-fill,minmax(18rem,1fr))]">
      <article
        v-for="kot in ordered"
        :key="kot.id"
        class="grid min-w-0 content-start gap-2 overflow-hidden rounded-lg border p-3 transition-colors"
        :class="kot.acknowledged_at ? 'border-border opacity-60' : 'border-amber-500/60 bg-amber-500/5'"
      >
        <button
          type="button"
          class="flex min-w-0 items-baseline gap-2 text-left outline-hidden focus-visible:ring-2 focus-visible:ring-ring"
          :title="`Open order #${kot.order_number}`"
          @click="router.push(`/pos/orders/${kot.order_id}`)"
        >
          <span class="text-base font-semibold">
            {{ kot.kind === 'takeaway' ? 'Takeaway' : kot.table_label }}
          </span>
          <span class="text-xs text-muted-foreground">KOT {{ kot.number }} · #{{ kot.order_number }}</span>
          <span class="ml-auto text-xs font-medium tabular-nums text-amber-700 dark:text-amber-400">
            {{ since(kot.sent_at) }}
          </span>
        </button>

        <ul class="grid min-w-0 gap-1">
          <li v-for="line in kot.lines" :key="line.line_id" class="flex min-w-0 gap-2 text-sm">
            <span class="w-6 shrink-0 tabular-nums text-muted-foreground">{{ line.quantity }}×</span>
            <span class="min-w-0 flex-1">
              <span class="block leading-snug break-words">{{ line.name }}</span>
              <span v-if="line.variation" class="block text-xs text-muted-foreground">{{ line.variation }}</span>
              <span v-if="line.note" class="block text-xs font-medium italic">“{{ line.note }}”</span>
            </span>
          </li>
        </ul>

        <footer class="flex min-w-0 flex-wrap items-center gap-2 text-xs text-muted-foreground">
          <span class="min-w-0 truncate">{{ origin(kot) }}</span>
          <span class="ml-auto flex items-center gap-1">
            <Button variant="outline" size="sm" class="h-8" @click="emit('print', kot)">
              <FontAwesomeIcon :icon="['fas', 'print']" />
              Print
            </Button>
            <Button
              size="sm"
              class="h-8"
              :variant="kot.acknowledged_at ? 'outline' : 'default'"
              :disabled="busy === kot.id || Boolean(kot.acknowledged_at)"
              @click="acknowledge(kot)"
            >
              <FontAwesomeIcon :icon="['fas', busy === kot.id ? 'spinner' : 'check']" :class="busy === kot.id ? 'motion-safe:animate-spin' : ''" />
              {{ kot.acknowledged_at ? 'Acked' : 'Acknowledge' }}
            </Button>
          </span>
        </footer>
      </article>
    </div>
  </section>
</template>
