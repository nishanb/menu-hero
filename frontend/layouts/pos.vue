<script setup lang="ts">
/**
 * The till's shell: edge to edge, nothing but the work.
 *
 * A POS terminal is a screen that is on all shift, at arm's length, tapped with a thumb
 * between carrying plates. The management app's rail, its page margins and its reading
 * column are all wrong for that, so this layout hands the page the whole viewport and keeps
 * one slim bar: where you are, the time, a way out. Nothing scrolls at the page level; each
 * screen lays itself out inside the viewport and scrolls its own panels.
 */
import { useIntervalFn } from '@vueuse/core'
import { HOME_PATH } from '~/composables/useSession'

const { active, refresh } = useRestaurants()

/** A clock, because the terminal is the one screen in the room that is always facing you. */
const now = ref(new Date())
const clock = computed(
  () => new Intl.DateTimeFormat('en-IN', { hour: '2-digit', minute: '2-digit' }).format(now.value),
)
const { resume } = useIntervalFn(() => {
  now.value = new Date()
}, 1000, { immediate: false })

onMounted(() => {
  resume()
  refresh().catch(() => {
    // The memberships from `/session` are the fallback, and they are already on screen.
  })
})
</script>

<template>
  <div class="flex h-dvh flex-col overflow-hidden bg-background text-foreground print:block print:h-auto print:overflow-visible">
    <header class="flex h-11 shrink-0 items-center gap-3 border-b border-border px-3 print:hidden">
      <NuxtLink to="/pos" class="flex items-center gap-2 text-sm font-semibold tracking-tight">
        <FontAwesomeIcon :icon="['fas', 'cash-register']" />
        POS
      </NuxtLink>
      <span v-if="active" class="truncate text-sm text-muted-foreground">{{ active.name }}</span>
      <div class="ml-auto flex items-center gap-2">
        <ClientOnly>
          <span class="text-sm tabular-nums">{{ clock }}</span>
        </ClientOnly>
        <Button variant="ghost" size="sm" as-child>
          <NuxtLink :to="HOME_PATH">
            <FontAwesomeIcon :icon="['fas', 'right-from-bracket']" />
            Exit
          </NuxtLink>
        </Button>
      </div>
    </header>

    <main id="main" class="flex min-h-0 flex-1 flex-col print:block print:h-auto">
      <slot />
    </main>
  </div>
</template>
