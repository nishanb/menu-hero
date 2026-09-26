<script setup lang="ts">
/**
 * "How should it come?" - the one question a dish with forms has to ask before Add.
 *
 * A sheet from the bottom, because the thumb is at the bottom. Each form is a full-width
 * row with its own price, and tapping one is the answer: no radio, no confirm.
 */
import type { PublicItem, PublicVariation } from '~/types/api'
import { price } from '~/utils/pos'

defineProps<{ item: PublicItem | null }>()

const open = defineModel<boolean>('open', { default: false })

const emit = defineEmits<{ choose: [item: PublicItem, variation: PublicVariation] }>()
</script>

<template>
  <Sheet v-model:open="open">
    <SheetContent side="bottom" class="mx-auto w-full max-w-md rounded-t-2xl pb-[max(1rem,env(safe-area-inset-bottom))]">
      <SheetHeader class="text-left">
        <SheetTitle>{{ item?.name }}</SheetTitle>
        <SheetDescription>How should it come?</SheetDescription>
      </SheetHeader>
      <div class="grid gap-2 px-4">
        <Button
          v-for="variation in item?.variations ?? []"
          :key="variation.name"
          variant="outline"
          class="h-12 justify-between text-base"
          @click="item && emit('choose', item, variation)"
        >
          <span>{{ variation.name }}</span>
          <span class="tabular-nums">₹{{ price.format(variation.price) }}</span>
        </Button>
      </div>
    </SheetContent>
  </Sheet>
</template>
