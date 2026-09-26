<script setup lang="ts">
import type { DropdownMenuSubTriggerProps } from 'reka-ui'

import type { HTMLAttributes } from 'vue'
/*
 * Font Awesome instead of the registry's `@lucide/vue` icon: that package's icon wrapper
 * calls `inject()` outside of setup, which warns during SSR and then hydrates to a
 * different node ("Hydration node mismatch"). Font Awesome is already registered globally
 * for the rest of the app, so this drops a dependency rather than adding one. Re-running
 * `shadcn-vue add` for this component will put the lucide import back.
 */
import { reactiveOmit } from '@vueuse/core'
import {
  DropdownMenuSubTrigger,
  useForwardProps,
} from 'reka-ui'
import { cn } from '@/lib/utils'

const props = defineProps<DropdownMenuSubTriggerProps & { class?: HTMLAttributes['class'], inset?: boolean }>()

const delegatedProps = reactiveOmit(props, 'class', 'inset')
const forwardedProps = useForwardProps(delegatedProps)
</script>

<template>
  <DropdownMenuSubTrigger
    data-slot="dropdown-menu-sub-trigger"
    :data-inset="inset ? '' : undefined"
    v-bind="forwardedProps"
    :class="cn(
      'focus:bg-accent focus:text-accent-foreground data-open:bg-accent data-open:text-accent-foreground not-data-[variant=destructive]:focus:**:text-accent-foreground gap-1.5 rounded-md px-1.5 py-1 text-sm data-inset:pl-7 [&_svg:not([class*=size-])]:size-4 flex cursor-default items-center outline-hidden select-none [&_svg]:pointer-events-none [&_svg]:shrink-0',
      props.class,
    )"
  >
    <slot />
    <FontAwesomeIcon :icon="['fas', 'chevron-right']" class="cn-rtl-flip ml-auto" />
  </DropdownMenuSubTrigger>
</template>
