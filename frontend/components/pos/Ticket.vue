<script setup lang="ts">
/**
 * The order as the table has built it: pending lines on top, sent tickets below.
 *
 * The split is the whole point. What the kitchen has not been told about is editable and
 * sits under a "to send" heading; what it has been told about is grouped by ticket and
 * cannot be touched, because changing the record without changing the ticket is how a
 * kitchen gets lied to. The count on the Send button is the thing a server checks before
 * walking away from the terminal.
 */
import type { Order, OrderLine } from '~/types/api'

const props = defineProps<{ order: Order, busyLine?: string }>()

const emit = defineEmits<{
  quantity: [line: OrderLine, quantity: number]
  note: [line: OrderLine, note: string]
  remove: [line: OrderLine]
}>()

const money = new Intl.NumberFormat('en-IN', { minimumFractionDigits: 2 })

const pending = computed(() => props.order.lines.filter(line => !line.kot_id))

/** Sent lines, grouped by the ticket they went on, in the order the tickets went. */
const sent = computed(() => {
  const groups = new Map<string, OrderLine[]>()
  for (const line of props.order.lines) {
    if (line.kot_id) {
      const list = groups.get(line.kot_id) ?? []
      list.push(line)
      groups.set(line.kot_id, list)
    }
  }
  return props.order.kot_ids
    .filter(id => groups.has(id))
    .map((id, index) => ({ id, number: index + 1, lines: groups.get(id) ?? [] }))
})

const editable = computed(() => props.order.status === 'open')

/** A note field is open for one line at a time; a ticket full of open fields is noise. */
const noting = ref<string | null>(null)
const draftNote = ref('')

async function openNote(line: OrderLine): Promise<void> {
  noting.value = line.id
  draftNote.value = line.note
  // `autofocus` only counts at page load; this field appears on a tap.
  await nextTick()
  document.getElementById(`note-${line.id}`)?.focus()
}

function saveNote(line: OrderLine): void {
  noting.value = null
  if (draftNote.value.trim() !== line.note) {
    emit('note', line, draftNote.value.trim())
  }
}
</script>

<template>
  <!-- `min-w-0` down the grid: a grid item is as wide as its content unless told otherwise,
       and the ticket lives in a fixed column that must never scroll sideways. -->
  <div class="grid min-w-0 gap-4">
    <p
      v-if="!order.lines.length"
      class="rounded-lg border border-dashed border-border px-4 py-10 text-center text-sm text-muted-foreground"
    >
      Nothing ordered yet. Tap a dish.
    </p>

    <!-- To send ------------------------------------------------------------- -->
    <section v-if="pending.length" class="grid min-w-0 gap-1.5">
      <p class="flex items-center justify-between text-xs font-medium text-amber-700 uppercase dark:text-amber-400">
        To send
        <span>{{ pending.length }}</span>
      </p>
      <div
        v-for="line in pending"
        :key="line.id"
        class="rounded-lg border border-amber-500/40 bg-amber-50/60 px-2.5 py-2 dark:bg-amber-500/10"
      >
        <div class="flex items-start gap-2">
          <div class="min-w-0 flex-1">
            <p class="text-sm leading-snug font-medium break-words">{{ line.name }}</p>
            <p v-if="line.variation" class="text-xs text-muted-foreground">{{ line.variation.name }}</p>
            <p v-if="line.note && noting !== line.id" class="text-xs text-muted-foreground italic">
              “{{ line.note }}”
            </p>
          </div>
          <p class="shrink-0 text-sm tabular-nums">{{ money.format(line.total) }}</p>
        </div>

        <div class="mt-1.5 flex items-center gap-1">
          <Button
            variant="outline"
            size="icon-sm"
            aria-label="One fewer"
            :disabled="!editable || busyLine === line.id || line.quantity <= 1"
            @click="emit('quantity', line, line.quantity - 1)"
          >
            <FontAwesomeIcon :icon="['fas', 'minus']" />
          </Button>
          <span class="w-7 text-center text-sm tabular-nums">{{ line.quantity }}</span>
          <Button
            variant="outline"
            size="icon-sm"
            aria-label="One more"
            :disabled="!editable || busyLine === line.id || line.quantity >= 99"
            @click="emit('quantity', line, line.quantity + 1)"
          >
            <FontAwesomeIcon :icon="['fas', 'plus']" />
          </Button>
          <Button
            variant="ghost"
            size="sm"
            class="h-7 px-2 text-xs"
            :disabled="!editable"
            @click="noting === line.id ? saveNote(line) : openNote(line)"
          >
            {{ noting === line.id ? 'Done' : line.note ? 'Edit note' : 'Note' }}
          </Button>
          <Button
            variant="ghost"
            size="icon-sm"
            class="ml-auto text-destructive hover:text-destructive"
            aria-label="Remove"
            :disabled="!editable || busyLine === line.id"
            @click="emit('remove', line)"
          >
            <FontAwesomeIcon :icon="['fas', 'trash-can']" />
          </Button>
        </div>

        <Input
          v-if="noting === line.id"
          :id="`note-${line.id}`"
          v-model="draftNote"
          class="mt-1.5 h-8 text-sm"
          maxlength="120"
          placeholder="For the kitchen — less spicy, no onion…"
          @keydown.enter.prevent="saveNote(line)"
          @keydown.escape="noting = null"
        />
      </div>
    </section>

    <!-- Sent --------------------------------------------------------------- -->
    <section v-for="group in sent" :key="group.id" class="grid min-w-0 gap-1">
      <p class="flex items-center justify-between text-xs font-medium text-muted-foreground uppercase">
        <span>
          <FontAwesomeIcon :icon="['fas', 'kitchen-set']" class="mr-1" />
          Sent · ticket {{ group.number }}
        </span>
        <span>{{ group.lines.length }}</span>
      </p>
      <div
        v-for="line in group.lines"
        :key="line.id"
        class="flex items-start gap-2 rounded-lg border border-border px-2.5 py-2"
      >
        <span class="w-6 shrink-0 text-sm tabular-nums text-muted-foreground">{{ line.quantity }}×</span>
        <div class="min-w-0 flex-1">
          <p class="text-sm leading-snug break-words">{{ line.name }}</p>
          <p v-if="line.variation" class="text-xs text-muted-foreground">{{ line.variation.name }}</p>
          <p v-if="line.note" class="text-xs text-muted-foreground italic">“{{ line.note }}”</p>
        </div>
        <p class="shrink-0 text-sm tabular-nums">{{ money.format(line.total) }}</p>
      </div>
    </section>

    <!-- Totals --------------------------------------------------------------- -->
    <dl v-if="order.lines.length" class="grid gap-1 border-t border-border pt-3 text-sm">
      <div class="flex justify-between text-muted-foreground">
        <dt>Subtotal</dt>
        <dd class="tabular-nums">{{ money.format(order.subtotal) }}</dd>
      </div>
      <div class="flex justify-between text-base font-semibold">
        <dt>Total</dt>
        <dd class="tabular-nums">{{ money.format(order.total) }}</dd>
      </div>
    </dl>
  </div>
</template>
