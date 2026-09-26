<script setup lang="ts">
/**
 * The round, before it goes: every line with its count, a note for the kitchen, the total,
 * and the one button that sends it.
 *
 * Notes live here rather than on the menu row because most dishes get none, and a field on
 * every row is noise. After sending, the sheet becomes the confirmation - the numbers the
 * kitchen and the counter will use - so the diner knows it landed without a second screen.
 */
import type { CartLine } from '~/composables/useDinerCart'
import type { PublicOrderOut } from '~/types/api'
import { money } from '~/utils/pos'

defineProps<{
  lines: CartLine[]
  total: number
  table: string | null
  sending: boolean
  error: string
  placed: PublicOrderOut | null
}>()

const open = defineModel<boolean>('open', { default: false })

const emit = defineEmits<{
  quantity: [key: string, quantity: number]
  note: [key: string, note: string]
  place: []
  done: []
}>()

/** One note open at a time; a sheet of open fields is noise. */
const noting = ref<string | null>(null)

/**
 * Focus by hand: `autofocus` only counts at page load, and this field appears on a tap.
 * The keyboard coming up with the field is the whole point of it on a phone.
 */
async function toggleNote(key: string): Promise<void> {
  noting.value = noting.value === key ? null : key
  await nextTick()
  if (noting.value === key) {
    document.getElementById(`note-${key}`)?.focus()
  }
}
</script>

<template>
  <Sheet v-model:open="open">
    <SheetContent
      side="bottom"
      class="mx-auto flex w-full max-w-md max-h-[88dvh] flex-col rounded-t-2xl pb-[max(1rem,env(safe-area-inset-bottom))]"
    >
      <!-- Sent: the confirmation ------------------------------------------------ -->
      <template v-if="placed">
        <SheetHeader class="text-left">
          <SheetTitle class="flex items-center gap-2">
            <span class="grid size-7 place-items-center rounded-full bg-emerald-600 text-white">
              <FontAwesomeIcon :icon="['fas', 'check']" class="text-sm" />
            </span>
            Sent to the kitchen
          </SheetTitle>
          <SheetDescription>
            Order #{{ placed.order_number }} · ticket {{ placed.kot_number }}
            <template v-if="placed.table_label"> · table {{ placed.table_label }}</template>
          </SheetDescription>
        </SheetHeader>
        <p class="px-4 text-sm text-muted-foreground">
          Anything more goes on the same bill — order it the same way. Pay at the counter
          when you are done.
        </p>
        <div class="px-4 pt-4">
          <Button class="h-12 w-full text-base" @click="emit('done')">Order more</Button>
        </div>
      </template>

      <!-- Not yet: the round ---------------------------------------------------- -->
      <template v-else>
        <SheetHeader class="text-left">
          <SheetTitle>Your order</SheetTitle>
          <SheetDescription>
            <template v-if="table">Table {{ table }} · </template>goes straight to the kitchen
          </SheetDescription>
        </SheetHeader>

        <Alert v-if="error" variant="destructive" class="mx-4">
          <AlertDescription>{{ error }}</AlertDescription>
        </Alert>

        <div class="min-h-0 flex-1 overflow-y-auto px-4">
          <div v-for="line in lines" :key="line.key" class="border-b border-border py-3 last:border-0">
            <div class="flex items-start gap-3">
              <div class="min-w-0 flex-1">
                <p class="text-[15px] leading-snug font-medium break-words">{{ line.name }}</p>
                <p v-if="line.variation" class="text-xs text-muted-foreground">{{ line.variation }}</p>
                <p v-if="line.note && noting !== line.key" class="text-xs text-muted-foreground italic">
                  “{{ line.note }}”
                </p>
              </div>
              <div class="flex h-9 w-24 shrink-0 items-center justify-between rounded-lg border border-primary text-primary">
                <button type="button" class="grid h-full w-8 place-items-center" aria-label="One fewer" @click="emit('quantity', line.key, line.quantity - 1)">
                  <FontAwesomeIcon :icon="['fas', line.quantity === 1 ? 'trash-can' : 'minus']" />
                </button>
                <span class="text-sm font-semibold tabular-nums">{{ line.quantity }}</span>
                <button type="button" class="grid h-full w-8 place-items-center" aria-label="One more" @click="emit('quantity', line.key, line.quantity + 1)">
                  <FontAwesomeIcon :icon="['fas', 'plus']" />
                </button>
              </div>
            </div>
            <div class="mt-1.5 flex items-center justify-between gap-3">
              <button
                type="button"
                class="text-xs text-muted-foreground underline-offset-2 hover:underline"
                @click="toggleNote(line.key)"
              >
                {{ noting === line.key ? 'Done' : line.note ? 'Edit note' : 'Add a note for the kitchen' }}
              </button>
              <span class="text-sm tabular-nums">₹{{ money.format(line.unit_price * line.quantity) }}</span>
            </div>
            <Input
              v-if="noting === line.key"
              :id="`note-${line.key}`"
              :model-value="line.note"
              class="mt-2 h-10"
              maxlength="120"
              placeholder="Less spicy, no onion…"
              @update:model-value="emit('note', line.key, String($event))"
              @keydown.enter.prevent="noting = null"
            />
          </div>
        </div>

        <div class="grid gap-3 border-t border-border px-4 pt-3">
          <div class="flex items-baseline justify-between">
            <span class="text-sm text-muted-foreground">Total</span>
            <span class="text-lg font-semibold tabular-nums">₹{{ money.format(total) }}</span>
          </div>
          <Button class="h-12 w-full text-base" :disabled="!lines.length || sending || !table" @click="emit('place')">
            <FontAwesomeIcon v-if="sending" :icon="['fas', 'spinner']" class="motion-safe:animate-spin" />
            {{ table ? 'Place order' : 'Ask a server to order' }}
          </Button>
        </div>
      </template>
    </SheetContent>
  </Sheet>
</template>
