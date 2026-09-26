<script setup lang="ts">
/**
 * One dish on the phone: picture if there is one, name, what it is, the price, and Add.
 *
 * The diet mark is the Indian convention - a green square for veg, red for non-veg -
 * because that is what every diner here reads before the name. Every row has a picture
 * square, a stand-in when there is no photo, so the list keeps one rhythm. Once a dish is
 * in the cart the button becomes a stepper, so "one more" is a tap and not a trip to the
 * cart.
 */
import type { PublicItem } from '~/types/api'
import { price } from '~/utils/pos'

defineProps<{ item: PublicItem, quantity: number }>()

const emit = defineEmits<{ add: [item: PublicItem], less: [item: PublicItem] }>()

function dietClass(diet: string): string {
  if (diet === 'veg') {
    return 'border-emerald-600 text-emerald-600'
  }
  if (diet === 'non-veg') {
    return 'border-red-600 text-red-600'
  }
  return diet ? 'border-amber-500 text-amber-500' : 'hidden'
}
</script>

<template>
  <article class="flex gap-3 py-3">
    <div class="min-w-0 flex-1">
      <span
        class="mb-1 inline-grid size-3.5 place-items-center rounded-[3px] border"
        :class="dietClass(item.diet)"
        :aria-label="item.diet"
      >
        <span class="size-1.5 rounded-full bg-current" />
      </span>
      <h3 class="text-[15px] leading-snug font-medium">{{ item.name }}</h3>
      <p v-if="item.description" class="mt-0.5 line-clamp-2 text-[13px] text-muted-foreground">
        {{ item.description }}
      </p>
      <p class="mt-1 text-sm tabular-nums">
        <template v-if="item.variations.length">from </template>₹{{ price.format(item.price_from) }}
      </p>
    </div>

    <!-- The button rides the bottom edge of the photo, the way the food apps do it: one
         object to look at, not a picture and a control stacked with air between. -->
    <div class="relative w-24 shrink-0 self-start pb-3.5">
      <DinerDishPhoto :src="item.image_url" :diet="item.diet" />
      <div
        v-if="quantity && !item.variations.length"
        class="absolute inset-x-2 bottom-0 flex h-7 items-center justify-between rounded-md bg-primary text-primary-foreground shadow-md"
      >
        <button type="button" class="grid h-full w-7 place-items-center" aria-label="One fewer" @click="emit('less', item)">
          <FontAwesomeIcon :icon="['fas', 'minus']" class="text-[11px]" />
        </button>
        <span class="text-xs font-semibold tabular-nums">{{ quantity }}</span>
        <button type="button" class="grid h-full w-7 place-items-center" aria-label="One more" @click="emit('add', item)">
          <FontAwesomeIcon :icon="['fas', 'plus']" class="text-[11px]" />
        </button>
      </div>
      <Button
        v-else
        size="sm"
        class="absolute inset-x-2 bottom-0 h-7 px-0 text-xs font-semibold uppercase shadow-md"
        @click="emit('add', item)"
      >
        {{ quantity ? `Add · ${quantity}` : 'Add' }}
      </Button>
    </div>
  </article>
</template>
