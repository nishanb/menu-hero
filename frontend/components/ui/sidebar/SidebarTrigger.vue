<script setup lang="ts">
import type { HTMLAttributes } from 'vue'

/*
 * Font Awesome instead of the registry's `@lucide/vue` icon: that package's icon wrapper
 * calls `inject()` outside of setup, which warns during SSR and then hydrates to a
 * different node ("Hydration node mismatch"). Font Awesome is already registered globally
 * for the rest of the app, so this drops a dependency rather than adding one. Re-running
 * `shadcn-vue add` for this component will put the lucide import back.
 */
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { useSidebar } from './utils'

const props = defineProps<{
  class?: HTMLAttributes['class']
}>()

const { toggleSidebar } = useSidebar()
</script>

<template>
  <Button
    data-sidebar="trigger"
    data-slot="sidebar-trigger"
    variant="ghost"
    size="icon-sm"
    :class="cn('', props.class)"
    @click="toggleSidebar"
  >
    <FontAwesomeIcon :icon="['fas', 'bars']" />
    <span class="sr-only">Toggle Sidebar</span>
  </Button>
</template>
