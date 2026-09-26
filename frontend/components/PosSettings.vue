<script setup lang="ts">
/**
 * Which parts of the till this restaurant runs. Settings → POS.
 *
 * One switch, deliberately. Billing is the till proper - the floor plan and its tables,
 * takeaway bills, sending rounds, settling - and a restaurant whose orders arrive some other
 * way is better off with a POS that is only the kitchen's board. Kitchen tickets have no
 * switch: an order is a ticket wherever it comes from, and a kitchen that cannot see its
 * tickets is not a configuration, it is an outage - so that row says so and offers nothing.
 */
import { useClipboard } from '@vueuse/core'
import type { FloorPlan, Restaurant, RestaurantTable } from '~/types/api'
import { toApiError } from '~/utils/api-error'

const props = defineProps<{
  tenantId: string
  /** Owners edit; staff read. The backend refuses the write either way. */
  canManage: boolean
}>()

const api = useRestaurantApi()
const { upsert } = useRestaurants()
const origin = useRequestURL().origin
const { copy, copied, isSupported: canCopy } = useClipboard({ copiedDuring: 1500 })

/* ------------------------------------------------------------------ the table's links */

const plan = useFloorPlan(computed(() => props.tenantId))
const tables = computed<RestaurantTable[]>(() => (plan.saved.value as FloorPlan | null)?.tables ?? [])

/** What the QR code on each table encodes - here in the open, so it can be tried on a phone. */
function linkFor(table: RestaurantTable | null): string {
  const base = `${origin}/restaurant/${props.tenantId}/order`
  return table ? `${base}?table=${table.id}` : base
}

const lastCopied = ref('')

async function copyLink(url: string): Promise<void> {
  await copy(url)
  lastCopied.value = url
}

const restaurant = ref<Restaurant | null>(null)
const loading = ref(true)
const saving = ref(false)
const error = ref('')

const billing = computed(() => restaurant.value?.pos.billing ?? true)

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    restaurant.value = await api.get(props.tenantId)
  }
  catch (cause) {
    error.value = toApiError(cause).detail
  }
  finally {
    loading.value = false
  }
}

async function setBilling(value: boolean): Promise<void> {
  saving.value = true
  error.value = ''
  try {
    restaurant.value = await api.update(props.tenantId, { pos: { billing: value } })
    upsert(restaurant.value)
  }
  catch (cause) {
    error.value = toApiError(cause).detail
  }
  finally {
    saving.value = false
  }
}

watch(() => props.tenantId, load, { immediate: true })
</script>

<template>
  <div class="grid gap-5">
    <Alert v-if="error" variant="destructive">
      <FontAwesomeIcon :icon="['fas', 'circle-exclamation']" />
      <AlertTitle>That did not go through</AlertTitle>
      <AlertDescription>{{ error }}</AlertDescription>
    </Alert>

    <Alert v-if="!canManage">
      <FontAwesomeIcon :icon="['fas', 'lock']" />
      <AlertTitle>Read-only</AlertTitle>
      <AlertDescription>An owner of this restaurant can change what the POS runs.</AlertDescription>
    </Alert>

    <Skeleton v-if="loading" class="h-40 w-full rounded-xl" />

    <div v-else class="divide-y divide-border rounded-xl border border-border">
      <div class="flex items-start gap-4 px-4 py-4">
        <div class="min-w-0 flex-1">
          <Label for="pos-billing" class="text-sm font-medium">Billing — floor plan, tables &amp; takeaway</Label>
          <p class="mt-1 text-sm text-muted-foreground">
            The till: the floor plan and its tables, takeaway bills, sending rounds to the
            kitchen and settling. Switch it off and the POS is the kitchen display only — the
            KOT board, with no bills, no <em>New bill</em>, and no order can be opened.
          </p>
        </div>
        <Switch
          id="pos-billing"
          :model-value="billing"
          :disabled="!canManage || saving"
          @update:model-value="setBilling"
        />
      </div>

      <div class="flex items-start gap-4 px-4 py-4">
        <div class="min-w-0 flex-1">
          <p class="text-sm font-medium">Kitchen tickets (KOT)</p>
          <p class="mt-1 text-sm text-muted-foreground">
            Always on. Every round sent from the till, and every order a table places from
            its QR menu, becomes a numbered ticket on the POS's KOT board, where the kitchen
            acknowledges it or prints it. Nothing to configure.
          </p>
        </div>
        <Badge variant="secondary" class="mt-0.5 shrink-0">Always on</Badge>
      </div>
    </div>

    <!-- Order from the table: the links behind the QR codes -------------------------- -->
    <section class="grid gap-3">
      <div>
        <p class="text-sm font-medium">Order from the table</p>
        <p class="mt-1 text-sm text-muted-foreground">
          What each table's QR code opens: the menu on the diner's phone, with ordering
          straight to the kitchen. No sign-in. Open one on a phone to try it — the link
          without a table shows the menu only.
        </p>
      </div>
      <div class="divide-y divide-border rounded-xl border border-border">
        <div
          v-for="entry in [{ table: null as RestaurantTable | null, label: 'Menu only (door)' }, ...tables.map(table => ({ table, label: `Table ${table.label}` }))]"
          :key="entry.table?.id ?? 'door'"
          class="flex items-center gap-3 px-4 py-2.5"
        >
          <span class="w-28 shrink-0 text-sm font-medium">{{ entry.label }}</span>
          <code class="min-w-0 flex-1 truncate text-xs text-muted-foreground">{{ linkFor(entry.table) }}</code>
          <Button variant="ghost" size="sm" class="h-8 shrink-0" as-child>
            <a :href="linkFor(entry.table)" target="_blank" rel="noopener">
              <FontAwesomeIcon :icon="['fas', 'eye']" />
              Open
            </a>
          </Button>
          <Button
            v-if="canCopy"
            variant="outline"
            size="sm"
            class="h-8 w-20 shrink-0"
            @click="copyLink(linkFor(entry.table))"
          >
            <FontAwesomeIcon :icon="['fas', copied && lastCopied === linkFor(entry.table) ? 'check' : 'copy']" />
            {{ copied && lastCopied === linkFor(entry.table) ? 'Copied' : 'Copy' }}
          </Button>
        </div>
      </div>
    </section>
  </div>
</template>
