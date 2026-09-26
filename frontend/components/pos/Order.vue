<script setup lang="ts">
/**
 * One order, being built, on the whole screen: the menu filling the left, the ticket down
 * the right - the shape of every till, because it is the shape of the job. The server taps
 * dishes with one hand and reads what has gone on with the other eye.
 *
 * The buttons under the ticket are the whole lifecycle, and only the one that makes sense
 * right now is live: **Send** while there are lines the kitchen has not seen, **Bill** once
 * it has seen everything, **Cancel** until the money is taken. Bill *settles*: the receipt
 * prints, the order closes and the table is free in one tap, because at the counter "bill"
 * and "paid" are one moment and a table stuck in "billed" until somebody remembers a second
 * button is a table nobody can seat. The backend keeps the two steps apart, so a close that
 * fails after the bill leaves the order `billed` with **Paid** and **Reprint** on offer,
 * never lost.
 *
 * Printing goes through the browser like everything else here. The ticket or the bill is
 * rendered into a hidden print area, the page prints, and the area clears - one print
 * pipeline for both, and the kitchen ticket comes out on its own the moment it is sent.
 */
import type { Kot, MenuItem, MenuVariation, Order, OrderLine } from '~/types/api'
import { usePosPrinter } from '~/composables/usePosPrinter'
import { toApiError } from '~/utils/api-error'
import { newId } from '~/utils/ids'
import { since } from '~/utils/pos'

const props = defineProps<{ tenantId: string, orderId: string }>()

const api = useRestaurantApi()
const router = useRouter()

const order = ref<Order | null>(null)
const kots = ref<Kot[]>([])
const loading = ref(true)
const error = ref('')
const busy = ref('')
const busyLine = ref('')

const canSend = computed(() => order.value?.status === 'open' && (order.value?.pending_count ?? 0) > 0)
const canBill = computed(
  () => order.value?.status === 'open' && order.value.lines.length > 0 && order.value.pending_count === 0,
)
const canPay = computed(() => order.value?.status === 'billed')
const canCancel = computed(() => order.value?.status === 'open' || order.value?.status === 'billed')
const finished = computed(() => order.value?.status === 'closed' || order.value?.status === 'cancelled')

const STATUS_LABELS: Record<Order['status'], string> = {
  open: 'Open',
  billed: 'Billed — awaiting payment',
  closed: 'Paid',
  cancelled: 'Cancelled',
}

/* ------------------------------------------------------------------ printing */

const { job: printing, print } = usePosPrinter()

/* ------------------------------------------------------------------ the lifecycle */

async function run(label: string, action: () => Promise<void>): Promise<void> {
  busy.value = label
  error.value = ''
  try {
    await action()
  }
  catch (cause) {
    error.value = toApiError(cause).detail
  }
  finally {
    busy.value = ''
  }
}

/**
 * Tapping a dish that is already on the ticket, unsent and unannotated, means "one more",
 * not a second line: that is how every till behaves, and one line with a count is what the
 * kitchen wants to read. A line with a note is left alone — the next one may be plain.
 */
function add(item: MenuItem, variation: MenuVariation | null): void {
  void run('add', async () => {
    const existing = order.value?.lines.find(line =>
      !line.kot_id
      && line.item_id === item.id
      && (line.variation?.name ?? null) === (variation?.name ?? null)
      && !line.note,
    )
    if (existing && existing.quantity < 99) {
      order.value = await api.updateLine(props.tenantId, props.orderId, existing.id, {
        quantity: existing.quantity + 1,
      })
      return
    }
    order.value = await api.addLines(props.tenantId, props.orderId, [
      { id: newId(), item_id: item.id, variation: variation?.name, quantity: 1 },
    ])
  })
}

async function changeQuantity(line: OrderLine, quantity: number): Promise<void> {
  busyLine.value = line.id
  error.value = ''
  try {
    order.value = await api.updateLine(props.tenantId, props.orderId, line.id, { quantity })
  }
  catch (cause) {
    error.value = toApiError(cause).detail
  }
  finally {
    busyLine.value = ''
  }
}

async function changeNote(line: OrderLine, note: string): Promise<void> {
  busyLine.value = line.id
  error.value = ''
  try {
    order.value = await api.updateLine(props.tenantId, props.orderId, line.id, { note })
  }
  catch (cause) {
    error.value = toApiError(cause).detail
  }
  finally {
    busyLine.value = ''
  }
}

async function remove(line: OrderLine): Promise<void> {
  busyLine.value = line.id
  error.value = ''
  try {
    order.value = await api.removeLine(props.tenantId, props.orderId, line.id)
  }
  catch (cause) {
    error.value = toApiError(cause).detail
  }
  finally {
    busyLine.value = ''
  }
}

/** Send, then print the ticket straight away - that is the moment the kitchen wants it. */
function send(): void {
  void run('send', async () => {
    const kot = await api.sendKot(props.tenantId, props.orderId)
    kots.value = [...kots.value, kot]
    order.value = await api.order(props.tenantId, props.orderId)
    await print({ kind: 'kot', kot })
  })
}

/** Bill, print, close, back to the floor: the table is free by the time the paper is torn off. */
function bill(): void {
  void run('bill', async () => {
    order.value = await api.billOrder(props.tenantId, props.orderId)
    await print({ kind: 'bill', order: order.value })
    order.value = await api.closeOrder(props.tenantId, props.orderId)
    await router.push('/pos')
  })
}

function reprintBill(): void {
  if (order.value) {
    void print({ kind: 'bill', order: order.value })
  }
}

function paid(): void {
  void run('pay', async () => {
    order.value = await api.closeOrder(props.tenantId, props.orderId)
    await router.push('/pos')
  })
}

const cancelOpen = ref(false)

function cancel(): void {
  void run('cancel', async () => {
    order.value = await api.cancelOrder(props.tenantId, props.orderId)
    await router.push('/pos')
  })
}

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const [found, tickets] = await Promise.all([
      api.order(props.tenantId, props.orderId),
      api.kots(props.tenantId, props.orderId),
    ])
    order.value = found
    kots.value = tickets.kots
  }
  catch (cause) {
    error.value = toApiError(cause).detail
  }
  finally {
    loading.value = false
  }
}

watch(() => [props.tenantId, props.orderId], load, { immediate: true })
</script>

<template>
  <div class="flex min-h-0 flex-1 flex-col gap-3 p-3 print:block print:h-auto print:p-0">
    <Alert v-if="error" variant="destructive" class="shrink-0 print:hidden">
      <FontAwesomeIcon :icon="['fas', 'circle-exclamation']" />
      <AlertTitle>That did not go through</AlertTitle>
      <AlertDescription>{{ error }}</AlertDescription>
    </Alert>

    <div v-if="loading" class="grid min-h-0 flex-1 gap-3 lg:grid-cols-[1fr_21rem]">
      <Skeleton class="rounded-xl" />
      <Skeleton class="rounded-xl" />
    </div>

    <div v-else-if="order" class="grid min-h-0 flex-1 gap-3 lg:grid-cols-[1fr_21rem] print:hidden">
      <!-- The menu ----------------------------------------------------------- -->
      <PosMenuPicker :tenant-id="tenantId" :disabled="order.status !== 'open'" @add="add" />

      <!-- The ticket --------------------------------------------------------- -->
      <aside class="flex min-h-0 min-w-0 flex-col rounded-xl border border-border bg-card">
        <div class="flex items-center gap-2 border-b border-border px-3 py-2.5">
          <Button variant="ghost" size="icon-sm" aria-label="Back to the floor" as-child>
            <NuxtLink to="/pos">
              <FontAwesomeIcon :icon="['fas', 'angles-left']" />
            </NuxtLink>
          </Button>
          <div class="min-w-0 flex-1">
            <p class="truncate text-lg leading-tight font-semibold">
              {{ order.kind === 'takeaway' ? 'Takeaway' : `Table ${order.table_label}` }}
            </p>
            <p class="text-xs text-muted-foreground">
              #{{ order.number }} · {{ STATUS_LABELS[order.status] }} · {{ since(order.opened_at) }}
            </p>
          </div>
          <Badge :variant="order.status === 'open' ? 'secondary' : 'outline'">
            {{ order.status }}
          </Badge>
        </div>

        <div class="min-h-0 flex-1 overflow-x-hidden overflow-y-auto p-3">
          <PosTicket
            :order="order"
            :busy-line="busyLine"
            @quantity="changeQuantity"
            @note="changeNote"
            @remove="remove"
          />
        </div>

        <!-- The lifecycle, in order. Only what makes sense now is live. Big, because this
             is the row a thumb finds without looking. -->
        <div v-if="!finished" class="grid grid-cols-2 gap-2 border-t border-border p-3">
          <Button class="h-12 text-base" :disabled="!canSend || Boolean(busy)" @click="send">
            <FontAwesomeIcon :icon="['fas', busy === 'send' ? 'spinner' : 'kitchen-set']" :class="busy === 'send' ? 'motion-safe:animate-spin' : ''" />
            Send{{ order.pending_count ? ` (${order.pending_count})` : '' }}
          </Button>
          <Button
            v-if="order.status === 'open'"
            variant="secondary"
            class="h-12 text-base"
            :disabled="!canBill || Boolean(busy)"
            @click="bill"
          >
            <FontAwesomeIcon :icon="['fas', busy === 'bill' ? 'spinner' : 'receipt']" :class="busy === 'bill' ? 'motion-safe:animate-spin' : ''" />
            Bill
          </Button>
          <template v-else>
            <Button variant="secondary" class="h-12 text-base" :disabled="Boolean(busy)" @click="reprintBill">
              <FontAwesomeIcon :icon="['fas', 'print']" />
              Reprint
            </Button>
            <Button class="col-span-2 h-12 text-base" :disabled="!canPay || Boolean(busy)" @click="paid">
              <FontAwesomeIcon :icon="['fas', busy === 'pay' ? 'spinner' : 'check']" :class="busy === 'pay' ? 'motion-safe:animate-spin' : ''" />
              Paid — free the table
            </Button>
          </template>
          <Button
            variant="ghost"
            class="col-span-2 h-10 text-destructive hover:text-destructive"
            :disabled="!canCancel || Boolean(busy)"
            @click="cancelOpen = true"
          >
            Cancel order
          </Button>
        </div>
        <p v-else class="border-t border-border px-3 py-3 text-sm text-muted-foreground">
          This order is {{ order.status }}. Nothing more can be done with it.
        </p>
      </aside>
    </div>

    <PosPrintSheets :job="printing" />

    <ClientOnly>
      <AlertDialog v-model:open="cancelOpen">
        <AlertDialogContent>
          <AlertDialogTitle>Cancel order #{{ order?.number }}?</AlertDialogTitle>
          <AlertDialogDescription>
            <template v-if="order?.kot_ids.length">
              {{ order.kot_ids.length }} {{ order.kot_ids.length === 1 ? 'ticket has' : 'tickets have' }}
              already gone to the kitchen. Tell them — this does not.
            </template>
            <template v-else>
              Nothing has gone to the kitchen.
              {{ order?.table_id ? 'The table goes back to free.' : 'The bill is dropped.' }}
            </template>
          </AlertDialogDescription>
          <AlertDialogFooter>
            <AlertDialogCancel>Keep it</AlertDialogCancel>
            <AlertDialogAction variant="destructive" @click="cancel">Cancel order</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </ClientOnly>
  </div>
</template>
