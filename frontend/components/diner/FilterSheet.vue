<script setup lang="ts">
/**
 * The filters, in a sheet - what you eat, what you will spend, which way round.
 *
 * Off the page and behind one button, because a menu is for reading and a row of chips
 * above it is not. Everything applies the moment it is tapped (the count on the close
 * button says how many dishes are left), and Clear puts it all back.
 */
const DIETS = [
  { value: 'veg', label: 'Veg', mark: 'border-emerald-600 text-emerald-600' },
  { value: 'non-veg', label: 'Non-veg', mark: 'border-red-600 text-red-600' },
  { value: 'egg', label: 'Egg', mark: 'border-amber-500 text-amber-500' },
] as const

const SORTS = [
  { value: '', label: 'Recommended' },
  { value: 'asc', label: 'Price: low to high' },
  { value: 'desc', label: 'Price: high to low' },
] as const

defineProps<{ priceCap: number, matches: number }>()

const open = defineModel<boolean>('open', { default: false })
const diets = defineModel<Set<string>>('diets', { required: true })
const underCap = defineModel<boolean>('underCap', { required: true })
const sort = defineModel<'' | 'asc' | 'desc'>('sort', { required: true })

function toggleDiet(value: string): void {
  const next = new Set(diets.value)
  if (next.has(value)) {
    next.delete(value)
  }
  else {
    next.add(value)
  }
  diets.value = next
}

function clear(): void {
  diets.value = new Set()
  underCap.value = false
  sort.value = ''
}
</script>

<template>
  <Sheet v-model:open="open">
    <SheetContent side="bottom" class="mx-auto w-full max-w-md rounded-t-2xl pb-[max(1rem,env(safe-area-inset-bottom))]">
      <SheetHeader class="text-left">
        <SheetTitle>Filters</SheetTitle>
        <SheetDescription>Narrow the menu to what you are after.</SheetDescription>
      </SheetHeader>

      <div class="grid gap-5 px-4">
        <section class="grid gap-2">
          <p class="text-xs font-medium text-muted-foreground uppercase">Diet</p>
          <div class="flex flex-wrap gap-2">
            <button
              v-for="diet in DIETS"
              :key="diet.value"
              type="button"
              class="flex items-center gap-2 rounded-full border px-3.5 py-2 text-sm transition-colors"
              :class="diets.has(diet.value) ? 'border-primary bg-primary text-primary-foreground' : 'border-border'"
              :aria-pressed="diets.has(diet.value)"
              @click="toggleDiet(diet.value)"
            >
              <span class="inline-grid size-3 place-items-center rounded-[2px] border" :class="diet.mark">
                <span class="size-1.5 rounded-full bg-current" />
              </span>
              {{ diet.label }}
            </button>
          </div>
        </section>

        <section class="grid gap-2">
          <p class="text-xs font-medium text-muted-foreground uppercase">Price</p>
          <button
            type="button"
            class="w-fit rounded-full border px-3.5 py-2 text-sm transition-colors"
            :class="underCap ? 'border-primary bg-primary text-primary-foreground' : 'border-border'"
            :aria-pressed="underCap"
            @click="underCap = !underCap"
          >
            Under ₹{{ priceCap }}
          </button>
        </section>

        <section class="grid gap-2">
          <p class="text-xs font-medium text-muted-foreground uppercase">Sort by</p>
          <div class="grid overflow-hidden rounded-xl border border-border">
            <button
              v-for="option in SORTS"
              :key="option.value"
              type="button"
              class="flex items-center justify-between border-b border-border px-4 py-3 text-left text-sm last:border-0"
              :class="sort === option.value ? 'bg-accent font-medium' : ''"
              :aria-pressed="sort === option.value"
              @click="sort = option.value"
            >
              {{ option.label }}
              <FontAwesomeIcon v-if="sort === option.value" :icon="['fas', 'check']" class="text-xs" />
            </button>
          </div>
        </section>
      </div>

      <div class="grid grid-cols-[auto_1fr] gap-2 px-4 pt-5">
        <Button variant="outline" class="h-12" @click="clear">Clear</Button>
        <Button class="h-12 text-base" @click="open = false">
          Show {{ matches }} {{ matches === 1 ? 'dish' : 'dishes' }}
        </Button>
      </div>
    </SheetContent>
  </Sheet>
</template>
