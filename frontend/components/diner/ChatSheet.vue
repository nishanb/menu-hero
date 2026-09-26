<script setup lang="ts">
/**
 * Chat and order: ask in words, get dishes back, tap Add.
 *
 * A sheet that is nearly the whole screen, because a conversation wants room. Messages
 * stack up from the top; the field stays at the thumb. The answers come from
 * `useMenuAssistant` today - a search over the loaded menu that talks - and from the agent
 * once it is wired in; this component does not care which, it only knows the shape.
 */
import type { PublicItem, PublicSection } from '~/types/api'
import { SUGGESTIONS, answer } from '~/composables/useMenuAssistant'
import { price } from '~/utils/pos'

const props = defineProps<{ sections: PublicSection[], restaurant: string }>()

const open = defineModel<boolean>('open', { default: false })

const emit = defineEmits<{ add: [item: PublicItem] }>()

interface Message {
  id: number
  from: 'you' | 'assistant'
  text: string
  items?: PublicItem[]
}

const messages = ref<Message[]>([])
const draft = ref('')
const thinking = ref(false)
const thread = ref<HTMLElement | null>(null)
let nextId = 1

/** A beat before the answer: instant replies read as canned, and the real agent will not be instant either. */
const THINK_MS = 650

function greet(): void {
  if (!messages.value.length) {
    messages.value.push({
      id: nextId++,
      from: 'assistant',
      text: `Hi! I know everything on the ${props.restaurant} menu. Tell me what you feel like — a dish, veg or non-veg, a budget — and I'll find it.`,
    })
  }
}

watch(open, (isOpen) => {
  if (isOpen) {
    greet()
  }
})

async function scrollToEnd(): Promise<void> {
  await nextTick()
  thread.value?.scrollTo({ top: thread.value.scrollHeight, behavior: 'smooth' })
}

async function ask(text: string): Promise<void> {
  const question = text.trim()
  if (!question || thinking.value) {
    return
  }
  draft.value = ''
  messages.value.push({ id: nextId++, from: 'you', text: question })
  thinking.value = true
  await scrollToEnd()
  await new Promise(resolve => window.setTimeout(resolve, THINK_MS))
  const reply = answer(question, props.sections)
  messages.value.push({ id: nextId++, from: 'assistant', text: reply.text, items: reply.items })
  thinking.value = false
  await scrollToEnd()
}
</script>

<template>
  <Sheet v-model:open="open">
    <SheetContent
      side="bottom"
      class="mx-auto flex w-full max-w-md flex-col gap-0 rounded-t-2xl p-0 pb-[max(0.5rem,env(safe-area-inset-bottom))] data-[side=bottom]:h-[92dvh]"
    >
      <SheetHeader class="border-b border-border px-4 py-3 text-left">
        <SheetTitle class="flex items-center gap-2 text-base">
          <span class="grid size-8 place-items-center rounded-full bg-primary text-primary-foreground">
            <FontAwesomeIcon :icon="['fas', 'robot']" class="text-sm" />
          </span>
          Chat &amp; order
        </SheetTitle>
        <SheetDescription>Ask for what you feel like; add it from here.</SheetDescription>
      </SheetHeader>

      <!-- The thread -->
      <div ref="thread" class="min-h-0 flex-1 overflow-y-auto px-4 py-3">
        <div class="grid gap-3">
          <div
            v-for="message in messages"
            :key="message.id"
            class="grid gap-2"
            :class="message.from === 'you' ? 'justify-items-end' : 'justify-items-start'"
          >
            <p
              class="max-w-[85%] rounded-2xl px-3.5 py-2 text-[15px] leading-snug"
              :class="message.from === 'you' ? 'rounded-br-md bg-primary text-primary-foreground' : 'rounded-bl-md bg-muted'"
            >
              {{ message.text }}
            </p>
            <div v-if="message.items?.length" class="grid w-full gap-2">
              <div
                v-for="item in message.items"
                :key="item.id"
                class="flex items-center gap-3 rounded-xl border border-border p-2"
              >
                <DinerDishPhoto :src="item.image_url" :diet="item.diet" class="!w-14 shrink-0" />
                <div class="min-w-0 flex-1">
                  <p class="text-sm leading-snug font-medium break-words">{{ item.name }}</p>
                  <p class="text-xs text-muted-foreground tabular-nums">
                    <template v-if="item.variations.length">from </template>₹{{ price.format(item.price_from) }}
                  </p>
                </div>
                <Button size="sm" class="h-8 shrink-0 text-xs font-semibold uppercase" @click="emit('add', item)">
                  Add
                </Button>
              </div>
            </div>
          </div>

          <div v-if="thinking" class="flex items-center gap-1 rounded-2xl rounded-bl-md bg-muted px-3.5 py-3 w-fit" aria-label="Thinking">
            <span v-for="n in 3" :key="n" class="size-1.5 rounded-full bg-muted-foreground/70 motion-safe:animate-bounce" :style="{ animationDelay: `${(n - 1) * 150}ms` }" />
          </div>
        </div>
      </div>

      <!-- Openers, until the conversation has started -->
      <div v-if="messages.length <= 1" class="flex gap-2 overflow-x-auto px-4 pb-2 [scrollbar-width:none]">
        <button
          v-for="suggestion in SUGGESTIONS"
          :key="suggestion"
          type="button"
          class="shrink-0 rounded-full border border-border px-3 py-1.5 text-sm whitespace-nowrap active:bg-accent"
          @click="ask(suggestion)"
        >
          {{ suggestion }}
        </button>
      </div>

      <!-- The field, at the thumb -->
      <form class="flex items-center gap-2 border-t border-border px-3 pt-2" @submit.prevent="ask(draft)">
        <Label for="diner-chat" class="sr-only">Ask for a dish</Label>
        <Input id="diner-chat" v-model="draft" placeholder="Something spicy under ₹200…" class="h-11 flex-1 rounded-full px-4 text-base" autocomplete="off" />
        <Button type="submit" size="icon" class="size-11 shrink-0 rounded-full" :disabled="!draft.trim() || thinking" aria-label="Send">
          <FontAwesomeIcon :icon="['fas', 'arrow-right']" />
        </Button>
      </form>
    </SheetContent>
  </Sheet>
</template>
