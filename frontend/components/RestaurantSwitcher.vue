<script setup lang="ts">
/**
 * The restaurant picker at the top of the rail: which restaurant you are working on, and a
 * way to add another.
 *
 * It no longer holds drafts. Creating a restaurant is a real thing that happens on the
 * server, and it needs a form long enough to deserve a page — so "New restaurant" is a
 * link to `/onboarding`, not a dialog. Switching writes the choice to the server
 * (`useRestaurants().select`) so it follows the person to their next device.
 */
import { toApiError } from '~/utils/api-error'

const { restaurants, active, activeId, select } = useRestaurants()

const ROLE_LABELS: Record<string, string> = { owner: 'Owner', staff: 'Staff' }

/** Shown briefly if the server refuses the switch; the list itself stays usable. */
const error = ref('')

/** First letter, for the tile that stands in for a restaurant's own mark. */
function initial(name: string): string {
  return name.trim().charAt(0).toUpperCase() || '?'
}

async function onSelect(id: string): Promise<void> {
  error.value = ''
  try {
    await select(id)
  }
  catch (cause) {
    error.value = toApiError(cause).detail
  }
}

/** An admin sees restaurants they hold no membership at; say so rather than guess a role. */
function subtitle(role: string | null): string {
  return role ? ROLE_LABELS[role] ?? role : 'Platform admin'
}
</script>

<template>
  <DropdownMenu>
    <DropdownMenuTrigger as-child>
      <button
        type="button"
        class="group/switch flex h-12 w-full items-center gap-2 rounded-lg px-2 text-left outline-hidden transition-colors hover:bg-sidebar-accent focus-visible:ring-2 focus-visible:ring-sidebar-ring data-[state=open]:bg-sidebar-accent group-data-[collapsible=icon]:size-8 group-data-[collapsible=icon]:justify-center group-data-[collapsible=icon]:p-0"
      >
        <!-- No restaurant chosen yet: the MenuHero mark stands in, so the rail is never
             headed by an empty square. -->
        <span
          v-if="!active"
          class="grid size-8 shrink-0 place-items-center rounded-lg bg-white shadow-sm ring-1 ring-black/5"
        >
          <img src="/brand-mark.png" alt="" width="17" height="20" class="h-[1.15rem] w-auto">
        </span>
        <span
          v-else-if="active.detail?.logo"
          class="size-8 shrink-0 overflow-hidden rounded-lg bg-white shadow-sm ring-1 ring-black/5"
        >
          <img :src="active.detail.logo" alt="" class="size-full object-cover">
        </span>
        <span
          v-else
          class="grid size-8 shrink-0 place-items-center rounded-lg bg-sidebar-primary text-sm font-semibold text-sidebar-primary-foreground"
        >
          {{ initial(active.name) }}
        </span>

        <span class="grid min-w-0 flex-1 leading-tight group-data-[collapsible=icon]:hidden">
          <span class="truncate text-sm font-semibold tracking-tight">
            {{ active?.name ?? 'MenuHero' }}
          </span>
          <span class="truncate text-xs text-sidebar-foreground/60">
            <template v-if="active">{{ subtitle(active.role) }}</template>
            <template v-else>No restaurant yet</template>
          </span>
        </span>

        <!-- The `hidden` sits on a wrapper, not on the icon: Font Awesome's stylesheet is
             unlayered and sets `display` on `.svg-inline--fa`, and an unlayered declaration
             beats anything in Tailwind's `utilities` layer whatever its specificity - so
             `hidden` on the svg itself is silently ignored and the chevron pokes out of the
             collapsed rail. -->
        <span class="shrink-0 group-data-[collapsible=icon]:hidden">
          <FontAwesomeIcon
            :icon="['fas', 'chevron-down']"
            class="text-xs text-sidebar-foreground/50 transition-transform group-data-[state=open]/switch:rotate-180"
          />
        </span>
      </button>
    </DropdownMenuTrigger>

    <DropdownMenuContent
      align="start"
      :side-offset="6"
      class="w-(--reka-dropdown-menu-trigger-width) min-w-56"
    >
      <DropdownMenuLabel class="text-[0.65rem] font-medium tracking-[0.12em] text-muted-foreground uppercase">
        Restaurants
      </DropdownMenuLabel>

      <DropdownMenuItem
        v-for="restaurant in restaurants"
        :key="restaurant.id"
        class="gap-2"
        @select="onSelect(restaurant.id)"
      >
        <span class="grid size-5 shrink-0 place-items-center rounded bg-muted text-[0.65rem] font-semibold">
          {{ initial(restaurant.name) }}
        </span>
        <span class="truncate">{{ restaurant.name }}</span>
        <FontAwesomeIcon
          v-if="activeId === restaurant.id"
          :icon="['fas', 'check']"
          class="ml-auto shrink-0"
        />
      </DropdownMenuItem>

      <p v-if="!restaurants.length" class="px-2 py-3 text-center text-xs text-muted-foreground">
        Nothing yet — set one up below, or wait for an owner to invite you.
      </p>

      <p v-if="error" class="px-2 py-1.5 text-xs text-destructive">{{ error }}</p>

      <DropdownMenuSeparator />

      <DropdownMenuItem as-child class="gap-2">
        <NuxtLink to="/onboarding">
          <FontAwesomeIcon :icon="['fas', 'plus']" class="text-muted-foreground" />
          <span>New restaurant</span>
        </NuxtLink>
      </DropdownMenuItem>
    </DropdownMenuContent>
  </DropdownMenu>
</template>
