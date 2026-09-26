<script setup lang="ts">
/**
 * The POS front door: one screen, three ways of looking at the shift.
 *
 * **KOTs** first - the queue of tickets the kitchen has not yet seen, to acknowledge (which
 * takes it off) or print - because whatever else the till is doing, that queue is what it
 * opens on and what the badge on the tab keeps in sight from the other views. Then the room: **Floor plan**, scaled to fit and
 * never scrolled (a till is glanced at from across the restaurant, and a table that is
 * off-screen is a table nobody seats), and **Tables**, the same tables as a list for a
 * server who thinks in "A4" rather than "by the window". Each takes the whole screen; the
 * takeaway bills sit in a strip underneath whichever is showing.
 *
 * Billing is a setting. Switched off, the POS is the kitchen display: the KOT board and
 * nothing else - no room, no takeaway, no **New bill** - for a restaurant whose orders arrive
 * some other way.
 *
 * A tap on a table seats it or opens what it is running up. That call is idempotent on the
 * backend, so two servers tapping A1 at once land on the same order.
 *
 * Polled every five seconds (HLD 3.3's board feed), because the floor changes under you:
 * the counter closes a bill on another device and the table should go green here without
 * anybody reloading.
 */
import { useIntervalFn } from '@vueuse/core'
import type { TableState } from '~/components/FloorPlanCanvas.vue'
import type { FloorPlan, Kot, Order, RestaurantTable } from '~/types/api'
import { usePosPrinter } from '~/composables/usePosPrinter'
import { toApiError } from '~/utils/api-error'
import { newId } from '~/utils/ids'
import { money, since } from '~/utils/pos'

const props = defineProps<{ tenantId: string }>()

const api = useRestaurantApi()
const router = useRouter()
const { active } = useRestaurants()
const { job: printing, print } = usePosPrinter()

/** Off, the POS is the kitchen display. Unknown (profile not loaded yet) reads as on. */
const billing = computed(() => active.value?.detail?.pos.billing ?? true)

/** The room views exist only while the till bills; the table list only with tables to list. */
const views = computed<Array<{ value: View, label: string, icon: string }>>(() => [
  { value: 'kots', label: 'KOTs', icon: 'kitchen-set' },
  ...(billing.value ? [{ value: 'floor' as const, label: 'Floor plan', icon: 'map' }] : []),
  ...(billing.value && tables.value.length ? [{ value: 'list' as const, label: 'Tables', icon: 'list' }] : []),
])

/** What is showing: the choice, unless a setting just took it away. */
const view = computed<View>(() =>
  views.value.some(option => option.value === chosen.value) ? chosen.value : 'kots',
)
const { savedElements, width, height, saved, loading: planLoading } = useFloorPlan(
  computed(() => props.tenantId),
)

const orders = ref<Order[]>([])
const kots = ref<Kot[]>([])
const loading = ref(true)
const error = ref('')
const busyTable = ref('')
type View = 'kots' | 'floor' | 'list'

const chosen = ref<View>('kots')

const tables = computed<RestaurantTable[]>(() => (saved.value as FloorPlan | null)?.tables ?? [])

/** The open or billed order at each table, by table id. */
const orderByTable = computed(() => {
  const map = new Map<string, Order>()
  for (const order of orders.value) {
    if (order.table_id && (order.status === 'open' || order.status === 'billed')) {
      map.set(order.table_id, order)
    }
  }
  return map
})

const states = computed<Record<string, TableState>>(() => {
  const out: Record<string, TableState> = {}
  for (const table of tables.value) {
    const order = orderByTable.value.get(table.id)
    out[table.id] = order ? (order.status === 'billed' ? 'billed' : 'open') : 'free'
  }
  return out
})

const takeaways = computed(() => orders.value.filter(order => order.kind === 'takeaway'))

const occupied = computed(() => orderByTable.value.size)

const freshKots = computed(() => kots.value.length)

async function load(): Promise<void> {
  try {
    const [active, tickets] = await Promise.all([
      api.orders(props.tenantId, 'active'),
      api.activeKots(props.tenantId),
    ])
    orders.value = active.orders
    kots.value = tickets.kots
    error.value = ''
  }
  catch (cause) {
    error.value = toApiError(cause).detail
  }
  finally {
    loading.value = false
  }
}

/** Seat a table, or go to what it is already running up. */
async function pickTable(tableId: string): Promise<void> {
  const running = orderByTable.value.get(tableId)
  if (running) {
    await router.push(`/pos/orders/${running.id}`)
    return
  }
  busyTable.value = tableId
  error.value = ''
  try {
    const order = await api.openOrder(props.tenantId, { table_id: tableId })
    await router.push(`/pos/orders/${order.id}`)
  }
  catch (cause) {
    error.value = toApiError(cause).detail
  }
  finally {
    busyTable.value = ''
  }
}

/**
 * The kitchen acknowledged a ticket. The board shows it as acked; the next poll (the
 * server no longer returns it) is what takes it off, so the tap has something to show for
 * itself before the tile goes.
 */
function noteAcked(seen: Kot): void {
  kots.value = kots.value.map(kot => (kot.id === seen.id ? seen : kot))
}

/** A bill with no table: the counter, a phone order, a delivery pickup. */
async function newTakeaway(): Promise<void> {
  busyTable.value = 'takeaway'
  error.value = ''
  try {
    const order = await api.openOrder(props.tenantId, { idempotency_key: newId() })
    await router.push(`/pos/orders/${order.id}`)
  }
  catch (cause) {
    error.value = toApiError(cause).detail
  }
  finally {
    busyTable.value = ''
  }
}

watch(() => props.tenantId, load, { immediate: true })
useIntervalFn(load, 5000)
</script>

<template>
  <div class="flex min-h-0 flex-1 flex-col gap-3 p-3 print:block print:h-auto print:p-0">
    <Alert v-if="error" variant="destructive" class="shrink-0 print:hidden">
      <FontAwesomeIcon :icon="['fas', 'circle-exclamation']" />
      <AlertTitle>That did not go through</AlertTitle>
      <AlertDescription>{{ error }}</AlertDescription>
    </Alert>

    <!-- The sections, and what is on ----------------------------------------- -->
    <div class="flex shrink-0 flex-wrap items-center gap-3 print:hidden">
      <div v-if="views.length > 1" class="flex rounded-lg border border-border p-0.5">
        <Button
          v-for="option in views"
          :key="option.value"
          variant="ghost"
          size="sm"
          class="h-9 px-3"
          :class="view === option.value ? 'bg-accent' : ''"
          @click="chosen = option.value"
        >
          <FontAwesomeIcon :icon="['fas', option.icon]" />
          {{ option.label }}
          <Badge
            v-if="option.value === 'kots' && freshKots"
            class="ml-1 h-5 min-w-5 justify-center bg-amber-500 px-1.5 text-black hover:bg-amber-500"
          >
            {{ freshKots }}
          </Badge>
        </Button>
      </div>
      <p class="flex items-center gap-2 text-sm text-muted-foreground">
        <template v-if="!billing">
          <FontAwesomeIcon :icon="['fas', 'kitchen-set']" />
          Kitchen display
          <Badge v-if="kots.length" class="bg-amber-500 text-black hover:bg-amber-500">{{ kots.length }}</Badge>
        </template>
        <template v-else-if="tables.length">{{ occupied }} of {{ tables.length }} tables seated</template>
        <template v-else>No tables yet</template>
        <template v-if="billing && takeaways.length"> · {{ takeaways.length }} takeaway</template>
      </p>
      <div v-if="billing" class="ml-auto flex items-center gap-3">
        <span v-if="view === 'floor' || view === 'list'" class="hidden items-center gap-3 text-xs text-muted-foreground sm:flex">
          <span class="flex items-center gap-1"><span class="size-2.5 rounded-full bg-emerald-500" /> Free</span>
          <span class="flex items-center gap-1"><span class="size-2.5 rounded-full bg-amber-500" /> Seated</span>
          <span class="flex items-center gap-1"><span class="size-2.5 rounded-full bg-sky-500" /> Billed</span>
        </span>
        <Button :disabled="busyTable === 'takeaway'" @click="newTakeaway">
          <FontAwesomeIcon :icon="['fas', busyTable === 'takeaway' ? 'spinner' : 'plus']" :class="busyTable === 'takeaway' ? 'motion-safe:animate-spin' : ''" />
          New bill
        </Button>
      </div>
    </div>

    <Skeleton v-if="loading || planLoading" class="min-h-0 flex-1 rounded-xl" />

    <template v-else>
      <!-- KOTs ----------------------------------------------------------------- -->
      <PosKotBoard
        v-if="view === 'kots'"
        :tenant-id="tenantId"
        :kots="kots"
        @acknowledged="noteAcked"
        @print="print({ kind: 'kot', kot: $event })"
      />

      <!-- No tables: the floor plan is where they come from ----------------------- -->
      <section
        v-else-if="view === 'floor' && !tables.length"
        class="grid min-h-0 flex-1 place-items-center rounded-xl border border-dashed border-border px-6 py-12 text-center"
      >
        <div>
          <p class="text-sm text-muted-foreground">
            There are no tables yet. Draw the floor plan and every table on it is a place an
            order can be opened for — or start a takeaway bill with <em>New bill</em>.
          </p>
          <Button size="sm" class="mt-4" as-child>
            <NuxtLink to="/settings?tab=floor-plan">Draw the floor plan</NuxtLink>
          </Button>
        </div>
      </section>

      <!-- Floor plan ------------------------------------------------------------- -->
      <FloorPlanCanvas
        v-else-if="view === 'floor'"
        class="min-h-0 flex-1"
        :elements="savedElements"
        :width="width"
        :height="height"
        :selected-id="null"
        :states="states"
        preview
        pickable
        fit
        @pick="pickTable"
      />

      <!-- Tables --------------------------------------------------------------- -->
      <div v-else class="min-h-0 flex-1 overflow-auto rounded-xl border border-border">
        <Table class="table-fixed">
          <TableHeader>
            <TableRow>
              <TableHead class="w-2" />
              <TableHead class="w-28">Table</TableHead>
              <TableHead class="w-20">Seats</TableHead>
              <TableHead>Order</TableHead>
              <TableHead class="w-24">Seated</TableHead>
              <TableHead class="w-28 text-right">Running</TableHead>
              <TableHead class="w-24" />
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableRow
              v-for="table in tables"
              :key="table.id"
              class="cursor-pointer"
              @click="pickTable(table.id)"
            >
              <TableCell class="p-0">
                <span
                  class="block h-9 w-1 rounded-full"
                  :class="{
                    free: 'bg-emerald-500',
                    open: 'bg-amber-500',
                    billed: 'bg-sky-500',
                  }[states[table.id] ?? 'free']"
                />
              </TableCell>
              <TableCell class="text-base font-medium">{{ table.label }}</TableCell>
              <TableCell class="text-muted-foreground">{{ table.seats || '—' }}</TableCell>
              <TableCell class="text-muted-foreground">
                <template v-if="orderByTable.get(table.id)">
                  #{{ orderByTable.get(table.id)!.number }} ·
                  {{ orderByTable.get(table.id)!.lines.length }}
                  {{ orderByTable.get(table.id)!.lines.length === 1 ? 'line' : 'lines' }}
                  <Badge v-if="orderByTable.get(table.id)!.status === 'billed'" variant="secondary" class="ml-1">
                    Billed
                  </Badge>
                  <Badge v-else-if="orderByTable.get(table.id)!.pending_count" variant="outline" class="ml-1">
                    {{ orderByTable.get(table.id)!.pending_count }} to send
                  </Badge>
                </template>
                <template v-else>Free</template>
              </TableCell>
              <TableCell class="text-muted-foreground">
                {{ orderByTable.get(table.id) ? since(orderByTable.get(table.id)!.opened_at) : '' }}
              </TableCell>
              <TableCell class="text-right tabular-nums">
                {{ orderByTable.get(table.id) ? money.format(orderByTable.get(table.id)!.total) : '' }}
              </TableCell>
              <TableCell class="text-right">
                <Button variant="ghost" size="sm" :disabled="busyTable === table.id">
                  {{ orderByTable.get(table.id) ? 'Open' : 'Seat' }}
                </Button>
              </TableCell>
            </TableRow>
          </TableBody>
        </Table>
      </div>

      <!-- Takeaway: bills with no table, under whichever room view is showing ----- -->
      <section v-if="billing && takeaways.length" class="grid shrink-0 gap-1.5 print:hidden">
        <p class="text-xs font-medium text-muted-foreground uppercase">Takeaway</p>
        <div class="flex gap-2 overflow-x-auto pb-1">
          <button
            v-for="order in takeaways"
            :key="order.id"
            type="button"
            class="flex w-56 shrink-0 items-center justify-between gap-3 rounded-lg border px-3 py-2 text-left transition-colors outline-hidden hover:bg-accent/60 focus-visible:ring-2 focus-visible:ring-ring"
            :class="order.status === 'billed' ? 'border-sky-500/60' : 'border-amber-500/60'"
            @click="router.push(`/pos/orders/${order.id}`)"
          >
            <span class="min-w-0">
              <span class="block text-sm font-medium">Bill #{{ order.number }}</span>
              <span class="block text-xs text-muted-foreground">
                {{ order.lines.length }} {{ order.lines.length === 1 ? 'line' : 'lines' }} ·
                {{ since(order.opened_at) }}
                <template v-if="order.status === 'billed'"> · billed</template>
              </span>
            </span>
            <span class="shrink-0 text-sm tabular-nums">{{ money.format(order.total) }}</span>
          </button>
        </div>
      </section>
    </template>

    <PosPrintSheets :job="printing" />
  </div>
</template>
