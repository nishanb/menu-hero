<script setup lang="ts">
/**
 * The signed-in shell: a fixed rail on the left, the page on the right.
 *
 * Separate from `default.vue`, which still carries the agent demo's own nav and the legacy
 * stylesheet. This one is shadcn/Tailwind only, so it follows the colour scheme — the
 * appearance switcher in the account menu is the single place the theme is chosen.
 *
 * The sidebar is shadcn-vue's, so the collapse behaviour, the mobile drawer, ⌘B and the
 * icon-rail tooltips come with it rather than being rebuilt here.
 */
import { HOME_PATH } from '~/composables/useSession'

const route = useRoute()
const colorMode = useColorMode()
const { user, role } = useSession()

/**
 * Read on the server too, so the first paint matches what the person left the rail set to.
 * `SidebarProvider` writes this cookie itself but defaults to "open" when it cannot see a
 * `document`, which is every server render — that mismatch is a visible jump on load.
 */
const sidebarOpen = useCookie<string | null>('sidebar_state')

const ROLE_LABELS: Record<string, string> = {
  admin: 'Platform admin',
  owner: 'Owner',
  staff: 'Staff',
  user: 'Member',
}

const roleLabel = computed(() => (role.value ? ROLE_LABELS[role.value] ?? role.value : ''))

/** Initials for the avatar, for the moment before Google's picture loads (or if it 404s). */
const initials = computed(() => {
  const source = user.value?.name || user.value?.email || ''
  const parts = source.split(/[\s@.]+/).filter(Boolean)
  return (parts[0]?.[0] ?? '') + (parts.length > 1 ? parts[1]![0] : '')
})

interface NavItem {
  label: string
  icon: string
  /** A row that links somewhere. Mutually exclusive with `children`. */
  to?: string
  /** A section: the row expands instead of navigating. */
  children?: Array<{ label: string, to: string }>
  soon?: boolean
}

/**
 * `soon` marks a section of the product that is not built yet. Shown, greyed and labelled,
 * rather than hidden: the shape of the app is the point of a rail, and a row that says so is
 * more honest than a link that 404s.
 */
const NAV: NavItem[] = [
  { label: 'Dashboard', icon: 'gauge', to: HOME_PATH },
  { label: 'POS', icon: 'cash-register', to: '/pos' },
  {
    label: 'Menus',
    icon: 'book-open',
    children: [
      { label: 'Menu', to: '/menus' },
      { label: 'Categories', to: '/menus/categories' },
      { label: 'Menu on/off', to: '/menus/availability' },
      { label: 'Import menu', to: '/menus/import' },
      { label: 'Physical menu', to: '/menus/physical' },
      { label: 'Table QR code', to: '/menus/qr-code' },
    ],
  },
  { label: 'Orders', icon: 'receipt', soon: true },
  { label: 'Kitchen', icon: 'bell-concierge', soon: true },
  { label: 'AI agent', icon: 'robot', to: '/agent' },
  { label: 'Settings', icon: 'gear', to: '/settings' },
]

/**
 * Which sections are unfolded. Closed until the person opens one, and nothing but a click on
 * the section row opens it — the route never does. It stays open across navigation because
 * the layout is not re-created between pages.
 */
const expanded = reactive<Record<string, boolean>>({})

/**
 * Fill the restaurant list once, in the browser.
 *
 * The rail renders correctly before this from the session's memberships; this adds what a
 * membership does not carry (logos, whether a restaurant came from Google) and keeps the
 * switcher honest after another device created one. Deliberately not awaited into SSR: a
 * failure here must never stop the shell rendering.
 */
const { refresh } = useRestaurants()

onMounted(() => {
  refresh().catch(() => {
    // The memberships from `/session` are the fallback, and they are already on screen.
  })
})

const APPEARANCES = [
  { value: 'system', label: 'System', icon: 'desktop' },
  { value: 'light', label: 'Light', icon: 'sun' },
  { value: 'dark', label: 'Dark', icon: 'moon' },
] as const

const appearanceLabel = computed(
  () => APPEARANCES.find(option => option.value === colorMode.preference)?.label ?? 'System',
)

const signingOut = ref(false)

async function onSignOut(): Promise<void> {
  signingOut.value = true
  try {
    await signOut()
  }
  finally {
    signingOut.value = false
  }
}
</script>

<template>
  <SidebarProvider :default-open="sidebarOpen !== 'false'">
    <Sidebar collapsible="icon">
      <SidebarHeader>
        <!-- Collapsed, the rail is one icon wide, so the switcher and the toggle stack
             instead of sitting side by side - and the toggle stays reachable, which is the
             only way back out of the rail apart from ⌘B. -->
        <div class="flex items-center gap-1 group-data-[collapsible=icon]:flex-col">
          <RestaurantSwitcher />
          <SidebarToggle class="shrink-0" />
        </div>
      </SidebarHeader>

      <SidebarContent>
        <SidebarGroup>
          <SidebarMenu>
            <SidebarMenuItem v-for="item in NAV" :key="item.label">
              <!-- A section: the row expands rather than going anywhere, and the pages
                   underneath are the links. Collapsed to the icon rail the sub-list hides
                   itself (the registry does that), so the chevron goes with it. -->
              <Collapsible
                v-if="item.children"
                :open="expanded[item.label]"
                class="group/section"
                @update:open="expanded[item.label] = $event"
              >
                <CollapsibleTrigger as-child>
                  <SidebarMenuButton :tooltip="item.label">
                    <FontAwesomeIcon :icon="['fas', item.icon]" />
                    <span>{{ item.label }}</span>
                    <!-- The chevron is wrapped because Font Awesome's own stylesheet is
                         unlayered and sets `display` on the icon, so `hidden` does nothing
                         when applied to it directly. -->
                    <span
                      class="ml-auto text-xs text-sidebar-foreground/50 transition-transform group-data-[state=open]/section:rotate-90 group-data-[collapsible=icon]:hidden"
                    >
                      <FontAwesomeIcon :icon="['fas', 'chevron-right']" />
                    </span>
                  </SidebarMenuButton>
                </CollapsibleTrigger>
                <CollapsibleContent>
                  <SidebarMenuSub>
                    <SidebarMenuSubItem v-for="child in item.children" :key="child.to">
                      <SidebarMenuSubButton as-child :is-active="route.path === child.to">
                        <NuxtLink :to="child.to">{{ child.label }}</NuxtLink>
                      </SidebarMenuSubButton>
                    </SidebarMenuSubItem>
                  </SidebarMenuSub>
                </CollapsibleContent>
              </Collapsible>

              <SidebarMenuButton
                v-else-if="item.to"
                as-child
                :is-active="route.path === item.to"
                :tooltip="item.label"
              >
                <NuxtLink :to="item.to">
                  <FontAwesomeIcon :icon="['fas', item.icon]" />
                  <span>{{ item.label }}</span>
                </NuxtLink>
              </SidebarMenuButton>
              <SidebarMenuButton
                v-else
                disabled
                :tooltip="`${item.label} — not built yet`"
                class="cursor-default opacity-50"
              >
                <FontAwesomeIcon :icon="['fas', item.icon]" />
                <span>{{ item.label }}</span>
              </SidebarMenuButton>
              <!-- No position override: the registry already places the badge per button
                   size, and hard-coding one only breaks when the row size changes. -->
              <SidebarMenuBadge v-if="item.soon" class="text-sidebar-foreground/50">
                Soon
              </SidebarMenuBadge>
            </SidebarMenuItem>
          </SidebarMenu>
        </SidebarGroup>
      </SidebarContent>

      <SidebarFooter>
        <SidebarMenu>
          <SidebarMenuItem>
            <DropdownMenu>
              <DropdownMenuTrigger as-child>
                <SidebarMenuButton size="lg" class="gap-2.5">
                  <Avatar class="size-7 rounded-full">
                    <AvatarImage v-if="user?.picture" :src="user.picture" alt="" referrerpolicy="no-referrer" />
                    <AvatarFallback class="text-[0.7rem]">{{ initials }}</AvatarFallback>
                  </Avatar>
                  <div class="grid min-w-0 flex-1 text-left leading-tight">
                    <span class="truncate text-sm font-medium">{{ user?.name || user?.email }}</span>
                    <span class="truncate text-xs text-sidebar-foreground/60">{{ roleLabel }}</span>
                  </div>
                  <FontAwesomeIcon :icon="['fas', 'ellipsis']" class="shrink-0 text-sidebar-foreground/50" />
                </SidebarMenuButton>
              </DropdownMenuTrigger>

              <DropdownMenuContent side="top" align="start" :side-offset="8" class="w-(--reka-dropdown-menu-trigger-width) min-w-60">
                <div class="px-2 py-1.5 leading-tight">
                  <div class="truncate text-sm font-medium">{{ user?.name || 'Signed in' }}</div>
                  <div class="truncate text-xs text-muted-foreground">{{ user?.email }}</div>
                </div>

                <DropdownMenuSeparator />

                <DropdownMenuSub>
                  <DropdownMenuSubTrigger>
                    <FontAwesomeIcon :icon="['fas', 'sun']" class="text-muted-foreground" />
                    <span>Appearance</span>
                    <span class="ml-auto pl-4 text-xs text-muted-foreground">{{ appearanceLabel }}</span>
                  </DropdownMenuSubTrigger>
                  <DropdownMenuSubContent class="min-w-36">
                    <DropdownMenuItem
                      v-for="option in APPEARANCES"
                      :key="option.value"
                      @select="colorMode.preference = option.value"
                    >
                      <FontAwesomeIcon :icon="['fas', option.icon]" class="text-muted-foreground" />
                      <span>{{ option.label }}</span>
                      <FontAwesomeIcon
                        v-if="colorMode.preference === option.value"
                        :icon="['fas', 'check']"
                        class="ml-auto"
                      />
                    </DropdownMenuItem>
                  </DropdownMenuSubContent>
                </DropdownMenuSub>

                <DropdownMenuSeparator />

                <DropdownMenuItem :disabled="signingOut" @select="onSignOut">
                  <FontAwesomeIcon
                    :icon="['fas', signingOut ? 'spinner' : 'right-from-bracket']"
                    :class="signingOut ? 'motion-safe:animate-spin text-muted-foreground' : 'text-muted-foreground'"
                  />
                  <span>{{ signingOut ? 'Signing out' : 'Sign out' }}</span>
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarFooter>

      <SidebarRail />
    </Sidebar>

    <SidebarInset>
      <!-- The rail is a drawer below 768px, so the phone needs its own way back to it. -->
      <header class="flex h-12 items-center gap-2 border-b border-border px-3 md:hidden">
        <SidebarToggle />
        <span class="text-sm font-semibold tracking-tight">MenuHero</span>
      </header>

      <main id="main" class="flex-1">
        <slot />
      </main>
    </SidebarInset>
  </SidebarProvider>
</template>
