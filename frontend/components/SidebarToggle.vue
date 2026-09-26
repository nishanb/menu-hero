<script setup lang="ts">
/**
 * Show or hide the rail.
 *
 * Its own component rather than the registry's `SidebarTrigger` because the icon has to say
 * which way the click goes: a single glyph for both states reads as decoration, and next to
 * the switcher's chevron there were two ambiguous shapes in a row. Chevrons point the way
 * the rail is about to move, and the phone gets the hamburger it expects, since there the
 * button opens a drawer rather than widening a column.
 */
import { useSidebar } from '@/components/ui/sidebar'

const { isMobile, state, toggleSidebar } = useSidebar()

const icon = computed(() => {
  if (isMobile.value) {
    return 'bars'
  }
  return state.value === 'expanded' ? 'angles-left' : 'angles-right'
})

const label = computed(() => {
  if (isMobile.value) {
    return 'Open the menu'
  }
  return state.value === 'expanded' ? 'Collapse the sidebar' : 'Expand the sidebar'
})
</script>

<template>
  <Button
    variant="ghost"
    size="icon-sm"
    :aria-label="label"
    :title="isMobile ? label : `${label} (⌘B)`"
    class="text-sidebar-foreground/50 hover:text-sidebar-foreground"
    @click="toggleSidebar"
  >
    <FontAwesomeIcon :icon="['fas', icon]" class="size-[0.9rem]" />
  </Button>
</template>
