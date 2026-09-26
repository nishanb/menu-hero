<script setup lang="ts">
/**
 * Settings for the restaurant currently in the switcher.
 *
 *   Restaurant  — the profile onboarding collected, editable
 *   Floor Plan  — the room as it is, with the editor itself behind a dialog
 *   Team        — members and invitations (this is where invitations moved to)
 *   Google      — the Business Profile connection, and re-syncing an imported restaurant
 *
 * The tab is in the query string so a link can point at one (`/settings?tab=team`, which
 * onboarding uses) and a reload comes back to the same place.
 *
 * The restaurant is re-fetched here rather than taken from the switcher: the list endpoint
 * omits logos, and this is the screen that edits one.
 */
import type { Restaurant, RestaurantUpdate } from '~/types/api'
import { fetchSession } from '~/composables/useSession'
import { toApiError } from '~/utils/api-error'

const api = useRestaurantApi()
const googleApi = useGoogleBusinessApi()
const route = useRoute()
const router = useRouter()
const { active, canManageActive, hasLoaded, upsert, refresh } = useRestaurants()

const TABS = ['restaurant', 'floor-plan', 'pos', 'team', 'google'] as const
type Tab = (typeof TABS)[number]

const tab = computed<Tab>({
  get: () => {
    const raw = route.query.tab
    return TABS.includes(raw as Tab) ? (raw as Tab) : 'restaurant'
  },
  set: (value) => {
    router.replace({ query: { ...route.query, tab: value } })
  },
})

/**
 * The floor plan is a canvas, and a canvas in a 3xl column is a letterbox. It is the one
 * tab that wants the width, so it is the one tab that gets it.
 */
const columnWidth = computed(() => (tab.value === 'floor-plan' ? 'max-w-6xl' : 'max-w-3xl'))

const restaurant = ref<Restaurant | null>(null)
const loading = ref(true)
const saving = ref(false)
const syncing = ref(false)
const error = ref('')
const saved = ref('')

async function load(): Promise<void> {
  const id = active.value?.id
  restaurant.value = null
  if (!id) {
    loading.value = false
    return
  }
  loading.value = true
  error.value = ''
  try {
    restaurant.value = await api.get(id)
  }
  catch (cause) {
    error.value = toApiError(cause).detail
  }
  finally {
    loading.value = false
  }
}

async function onSubmit(changes: RestaurantUpdate): Promise<void> {
  const id = restaurant.value?.id
  if (!id) {
    return
  }
  saving.value = true
  error.value = ''
  saved.value = ''
  try {
    const updated = await api.update(id, changes)
    restaurant.value = updated
    upsert(updated)
    // The rail reads the name from the session's memberships, so a rename has to go back
    // through it or the switcher keeps showing the old one.
    await fetchSession(true)
    saved.value = 'Saved.'
  }
  catch (cause) {
    error.value = toApiError(cause).detail
  }
  finally {
    saving.value = false
  }
}

async function onSync(): Promise<void> {
  const id = restaurant.value?.id
  if (!id) {
    return
  }
  syncing.value = true
  error.value = ''
  saved.value = ''
  try {
    const updated = await googleApi.sync(id)
    restaurant.value = updated
    upsert(updated)
    await fetchSession(true)
    saved.value = 'Refreshed from Google.'
  }
  catch (cause) {
    error.value = toApiError(cause).detail
  }
  finally {
    syncing.value = false
  }
}

/** A restaurant imported into the app by someone else appears here once it is refreshed. */
async function onImported(imported: Restaurant): Promise<void> {
  upsert(imported, { activate: true })
  await fetchSession(true)
  await refresh()
}

watch(() => active.value?.id, load, { immediate: true })

definePageMeta({ layout: 'app' })

useHead({ title: 'Settings' })
</script>

<template>
  <div class="mx-auto w-full px-5 pt-[5vh] pb-20 transition-[max-width]" :class="columnWidth">
    <header class="mb-6">
      <h1 class="text-[1.6rem] leading-tight font-normal tracking-[-0.02em]">Settings</h1>
      <p v-if="active" class="mt-1 text-sm text-muted-foreground">
        {{ active.name }}
        <span class="font-mono text-xs">· {{ active.slug }}</span>
      </p>
    </header>

    <!-- Still finding out. A platform admin holds no memberships, so the session alone
         says nothing about which restaurants they can see: without this they would be told
         they have none, and then watched it change its mind a moment later. -->
    <div v-if="!active && !hasLoaded" class="grid gap-4">
      <Skeleton class="h-9 w-64" />
      <Skeleton class="h-40 w-full" />
    </div>

    <!-- No restaurant at all: settings has nothing to be about. -->
    <section
      v-else-if="!active"
      class="rounded-xl border border-dashed border-border px-6 py-12 text-center"
    >
      <p class="text-sm text-muted-foreground">
        There is no restaurant to configure yet.
      </p>
      <Button class="mt-4" as-child>
        <NuxtLink to="/onboarding">Set up a restaurant</NuxtLink>
      </Button>
    </section>

    <template v-else>
      <Alert v-if="error" variant="destructive" class="mb-5">
        <FontAwesomeIcon :icon="['fas', 'circle-exclamation']" />
        <AlertTitle>That did not go through</AlertTitle>
        <AlertDescription>{{ error }}</AlertDescription>
      </Alert>

      <!-- Roomier than the registry default, which is sized for a dense toolbar: `px-1.5`
           leaves the selected pill hugging its label, which reads as a rendering fault
           rather than a selection. `!` on the height because the list's own
           `group-data-horizontal/tabs:h-8` is a variant selector and outranks a plain
           utility whatever the source order. -->
      <Tabs v-model="tab">
        <TabsList class="mb-6 h-10! max-w-full overflow-x-auto p-1">
          <TabsTrigger value="restaurant" class="px-4">Restaurant</TabsTrigger>
          <TabsTrigger value="floor-plan" class="px-4">Floor Plan</TabsTrigger>
          <TabsTrigger value="pos" class="px-4">POS</TabsTrigger>
          <TabsTrigger value="team" class="px-4">Team</TabsTrigger>
          <TabsTrigger value="google" class="px-4">Google</TabsTrigger>
        </TabsList>

        <!-- Profile ----------------------------------------------------------- -->
        <TabsContent value="restaurant">
          <div v-if="loading" class="grid gap-4">
            <Skeleton class="h-10 w-full" />
            <Skeleton class="h-24 w-full" />
            <Skeleton class="h-10 w-full" />
          </div>

          <template v-else-if="restaurant">
            <Alert v-if="!canManageActive" class="mb-6">
              <FontAwesomeIcon :icon="['fas', 'lock']" />
              <AlertTitle>Read-only</AlertTitle>
              <AlertDescription>
                An owner of this restaurant can change these details.
              </AlertDescription>
            </Alert>

            <p v-if="saved" class="mb-4 text-sm text-muted-foreground">{{ saved }}</p>

            <fieldset :disabled="!canManageActive" class="contents">
              <RestaurantForm
                :key="restaurant.id"
                :restaurant="restaurant"
                mode="edit"
                submit-label="Save changes"
                :busy="saving"
                @submit="onSubmit"
                @cancel="load"
              />
            </fieldset>
          </template>
        </TabsContent>

        <!-- Floor plan -------------------------------------------------------- -->
        <TabsContent value="floor-plan">
          <!-- Client-only: the plan is pointer-driven and measures nothing on the server,
               so rendering it there buys a skeleton and a hydration risk and nothing else. -->
          <ClientOnly>
            <template #fallback>
              <Skeleton class="h-96 w-full rounded-xl" />
            </template>
            <FloorPlanSettings :tenant-id="active.id" :can-manage="canManageActive" />
          </ClientOnly>
        </TabsContent>

        <!-- POS --------------------------------------------------------------- -->
        <TabsContent value="pos">
          <PosSettings :tenant-id="active.id" :can-manage="canManageActive" />
        </TabsContent>

        <!-- Team -------------------------------------------------------------- -->
        <TabsContent value="team">
          <TeamSettings :tenant-id="active.id" :can-manage="canManageActive" />
        </TabsContent>

        <!-- Google ------------------------------------------------------------ -->
        <TabsContent value="google">
          <div class="grid gap-6">
            <div
              v-if="restaurant?.google_location"
              class="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border bg-muted/40 px-4 py-3"
            >
              <div class="min-w-0">
                <p class="text-sm font-medium">{{ restaurant.name }} came from Google</p>
                <p class="mt-0.5 text-xs text-muted-foreground">
                  Refreshing overwrites the description, map link and contact details.
                  Anything you set here — services, diets, the logo — is left alone.
                </p>
              </div>
              <Button
                v-if="canManageActive"
                variant="outline"
                size="sm"
                :disabled="syncing"
                @click="onSync"
              >
                <FontAwesomeIcon
                  :icon="['fas', syncing ? 'spinner' : 'rotate']"
                  :class="syncing ? 'motion-safe:animate-spin' : ''"
                />
                Refresh from Google
              </Button>
            </div>

            <GoogleBusinessImport return-path="/settings?tab=google" @imported="onImported" />
          </div>
        </TabsContent>
      </Tabs>
    </template>
  </div>
</template>
