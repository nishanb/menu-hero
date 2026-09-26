<script setup lang="ts">
/**
 * The menu's table of contents, behind the floating Menu button.
 *
 * A menu with thirty sections cannot show them all at the top of the page, and a strip
 * that scrolls sideways hides most of them anyway. A list in a sheet shows every section
 * with how many dishes it has, and a tap jumps there - which is what the button on every
 * food app does.
 */
defineProps<{ sections: Array<{ name: string, count: number }> }>()

const open = defineModel<boolean>('open', { default: false })

const emit = defineEmits<{ jump: [name: string] }>()

function pick(name: string): void {
  open.value = false
  emit('jump', name)
}
</script>

<template>
  <Sheet v-model:open="open">
    <SheetContent side="bottom" class="mx-auto flex max-h-[80dvh] w-full max-w-md flex-col rounded-t-2xl pb-[max(1rem,env(safe-area-inset-bottom))]">
      <SheetHeader class="text-left">
        <SheetTitle>Menu</SheetTitle>
        <SheetDescription>Jump to a section.</SheetDescription>
      </SheetHeader>
      <div class="min-h-0 flex-1 overflow-y-auto px-4">
        <button
          v-for="section in sections"
          :key="section.name"
          type="button"
          class="flex w-full items-center justify-between border-b border-border py-3 text-left text-[15px] last:border-0"
          @click="pick(section.name)"
        >
          <span class="min-w-0 truncate">{{ section.name }}</span>
          <span class="ml-3 shrink-0 text-sm text-muted-foreground tabular-nums">{{ section.count }}</span>
        </button>
      </div>
    </SheetContent>
  </Sheet>
</template>
