<script setup lang="ts">
/*
 * Font Awesome instead of the registry's `@lucide/vue` icon: that package's icon wrapper
 * calls `inject()` outside of setup, which warns during SSR and then hydrates to a
 * different node ("Hydration node mismatch"). Font Awesome is already registered globally
 * for the rest of the app, so this drops a dependency rather than adding one. Re-running
 * `shadcn-vue add` for this component will put the lucide import back.
 */
import type { CheckboxRootEmits, CheckboxRootProps } from 'reka-ui'

import type { HTMLAttributes } from 'vue'
import { reactiveOmit } from '@vueuse/core'
import { CheckboxIndicator, CheckboxRoot, useForwardPropsEmits } from 'reka-ui'
import { cn } from '@/lib/utils'

const props = defineProps<CheckboxRootProps & { class?: HTMLAttributes['class'] }>()
const emits = defineEmits<CheckboxRootEmits>()

const delegatedProps = reactiveOmit(props, 'class')

const forwarded = useForwardPropsEmits(delegatedProps, emits)
</script>

<template>
  <CheckboxRoot
    v-slot="slotProps"
    data-slot="checkbox"
    v-bind="forwarded"
    :class="cn('border-input dark:bg-input/30 data-checked:bg-primary data-checked:text-primary-foreground dark:data-checked:bg-primary data-checked:border-primary aria-invalid:aria-checked:border-primary aria-invalid:border-destructive dark:aria-invalid:border-destructive/50 focus-visible:border-ring focus-visible:ring-ring/50 aria-invalid:ring-destructive/20 dark:aria-invalid:ring-destructive/40 flex size-4 items-center justify-center rounded-[4px] border transition-colors group-has-disabled/field:opacity-50 focus-visible:ring-3 aria-invalid:ring-3 peer relative shrink-0 outline-none after:absolute after:-inset-x-3 after:-inset-y-2 disabled:cursor-not-allowed disabled:opacity-50', props.class)"
  >
    <CheckboxIndicator
      data-slot="checkbox-indicator"
      class="[&>svg]:size-3.5 grid place-content-center text-current transition-none"
    >
      <slot v-bind="slotProps">
        <FontAwesomeIcon :icon="['fas', 'check']" class="text-[0.7em]" />
      </slot>
    </CheckboxIndicator>
  </CheckboxRoot>
</template>
