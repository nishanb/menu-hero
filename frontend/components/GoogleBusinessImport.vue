<script setup lang="ts">
/**
 * Import a restaurant from Google Business Profile.
 *
 * Three states, and the copy has to keep them apart or the screen is baffling:
 *
 * - **not configured** — the installation has no Google OAuth client, or no `SECRET_KEY`
 *   to encrypt the connection with. There is no feature switch; this is the only way the
 *   import can be unavailable.
 * - **not connected** — the person has not granted access yet.
 * - **connected** — their businesses are listed, each importable once.
 *
 * Whether Google will *answer* is a fourth thing, and not knowable up front: the Business
 * Profile APIs are allow-listed per Cloud project, so an unapproved one gets
 * `PERMISSION_DENIED` on the first listing. That arrives as an error with Google's reason
 * attached, rather than as a claim made before anyone has asked.
 *
 * `Connect` is a real browser navigation, not a fetch: the endpoint answers 307 to
 * accounts.google.com and a `$fetch` would die on CORS trying to follow it. This is the
 * same reason the login page uses an `<a href>`.
 */
import type { BusinessLocation, Restaurant } from '~/types/api'
import { toApiError } from '~/utils/api-error'

const props = defineProps<{
  /** Where Google should send the browser back to after consent. */
  returnPath: string
}>()

const emit = defineEmits<{ imported: [restaurant: Restaurant] }>()

const api = useGoogleBusinessApi()
const route = useRoute()

const status = ref<{ configured: boolean, connected: boolean, email: string }>({
  configured: false,
  connected: false,
  email: '',
})
const locations = ref<BusinessLocation[]>([])
const loading = ref(true)
const listing = ref(false)
const importingName = ref('')
const error = ref('')

/** Codes the callback can hand back, in the person's own terms. */
const CONNECT_ERRORS: Record<string, string> = {
  google_declined: 'Google sign-in was cancelled. Try connecting again when you are ready.',
  invalid_state: 'That connection attempt expired. Start it again from this page.',
  signed_out: 'Your session ended while you were at Google. Sign in and try again.',
  not_configured: 'This installation is missing the Google credentials the import needs.',
  no_refresh_token:
    'Google did not hand back a lasting permission. Remove MenuHero under your Google '
    + 'account’s third-party access, then connect again.',
}

const callbackError = computed(() => {
  const raw = route.query.error
  if (typeof raw !== 'string' || !raw) {
    return ''
  }
  return CONNECT_ERRORS[raw] ?? 'That connection did not finish. Try again from this page.'
})

const connectUrl = computed(() => googleBusinessConnectUrl(props.returnPath))

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const answer = await api.status()
    status.value = {
      configured: answer.configured,
      connected: answer.connection.connected,
      email: answer.connection.google_email,
    }
    if (answer.configured && answer.connection.connected) {
      await loadLocations()
    }
  }
  catch (cause) {
    error.value = toApiError(cause).detail
  }
  finally {
    loading.value = false
  }
}

async function loadLocations(): Promise<void> {
  listing.value = true
  error.value = ''
  try {
    locations.value = (await api.locations()).locations
  }
  catch (cause) {
    const failure = toApiError(cause)
    // 409 means the grant is gone: show the connect button again rather than an error the
    // person can do nothing about.
    if (failure.status === 409) {
      status.value = { ...status.value, connected: false }
    }
    else {
      error.value = failure.detail
    }
  }
  finally {
    listing.value = false
  }
}

async function importLocation(location: BusinessLocation): Promise<void> {
  importingName.value = location.name
  error.value = ''
  try {
    emit('imported', await api.import(location.name))
    await loadLocations()
  }
  catch (cause) {
    error.value = toApiError(cause).detail
  }
  finally {
    importingName.value = ''
  }
}

async function disconnect(): Promise<void> {
  try {
    await api.disconnect()
  }
  catch (cause) {
    error.value = toApiError(cause).detail
  }
  finally {
    locations.value = []
    status.value = { ...status.value, connected: false, email: '' }
  }
}

onMounted(load)
</script>

<template>
  <div class="grid gap-4">
    <Alert v-if="callbackError" variant="destructive">
      <FontAwesomeIcon :icon="['fas', 'circle-exclamation']" />
      <AlertTitle>Connection stopped</AlertTitle>
      <AlertDescription>{{ callbackError }}</AlertDescription>
    </Alert>

    <div v-if="loading" class="grid gap-2">
      <Skeleton class="h-20 w-full rounded-xl" />
      <Skeleton class="h-20 w-full rounded-xl" />
    </div>

    <!-- The deployment itself cannot do this ---------------------------------- -->
    <Alert v-else-if="!status.configured">
      <FontAwesomeIcon :icon="['fas', 'circle-info']" />
      <AlertTitle>Importing from Google is not available here</AlertTitle>
      <AlertDescription>
        This installation is missing the Google credentials the import needs. Set the
        restaurant up manually for now — nothing is lost, and an import can be connected
        later.
      </AlertDescription>
    </Alert>

    <!-- Connected: their businesses ------------------------------------------ -->
    <template v-else-if="status.connected">
      <div class="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border bg-muted/40 px-4 py-3">
        <p class="text-sm">
          <span class="text-muted-foreground">Connected</span>
          <template v-if="status.email"> as {{ status.email }}</template>
        </p>
        <div class="flex gap-2">
          <Button variant="ghost" size="sm" :disabled="listing" @click="loadLocations">
            <FontAwesomeIcon
              :icon="['fas', listing ? 'spinner' : 'rotate']"
              :class="listing ? 'motion-safe:animate-spin' : ''"
            />
            Refresh
          </Button>
          <Button variant="ghost" size="sm" @click="disconnect">Disconnect</Button>
        </div>
      </div>

      <Alert v-if="error" variant="destructive">
        <FontAwesomeIcon :icon="['fas', 'circle-exclamation']" />
        <AlertTitle>Google could not be read</AlertTitle>
        <AlertDescription>{{ error }}</AlertDescription>
      </Alert>

      <div v-if="listing" class="grid gap-2">
        <Skeleton class="h-24 w-full rounded-xl" />
      </div>

      <p v-else-if="!locations.length" class="rounded-lg border border-dashed border-border px-4 py-8 text-center text-sm text-muted-foreground">
        This Google account manages no businesses. Set the restaurant up manually instead.
      </p>

      <ul v-else class="grid gap-3">
        <li
          v-for="location in locations"
          :key="location.name"
          class="grid gap-3 rounded-xl border border-border bg-card p-4 sm:grid-cols-[1fr_auto] sm:items-center"
        >
          <div class="min-w-0">
            <p class="truncate font-medium">{{ location.title || location.store_code }}</p>
            <p v-if="location.address" class="mt-0.5 truncate text-sm text-muted-foreground">
              {{ location.address }}
            </p>
            <p v-if="location.primary_category" class="mt-1 text-xs text-muted-foreground">
              {{ location.primary_category }}
            </p>
          </div>
          <div class="flex items-center gap-2 sm:justify-end">
            <Badge v-if="location.imported" variant="secondary">Imported</Badge>
            <Button
              v-else
              size="sm"
              :disabled="Boolean(importingName)"
              @click="importLocation(location)"
            >
              <FontAwesomeIcon
                v-if="importingName === location.name"
                :icon="['fas', 'spinner']"
                class="motion-safe:animate-spin"
              />
              Import
            </Button>
          </div>
        </li>
      </ul>
    </template>

    <!-- Configured but not connected ----------------------------------------- -->
    <div v-else class="grid gap-4 rounded-xl border border-border bg-card p-5">
      <div>
        <h3 class="font-medium">Bring your details across from Google</h3>
        <p class="mt-1 text-sm leading-relaxed text-muted-foreground">
          Connect the Google account that manages your business and we will fill in the
          name, description, address and map link. You can change any of it afterwards.
        </p>
      </div>
      <Alert v-if="error" variant="destructive">
        <FontAwesomeIcon :icon="['fas', 'circle-exclamation']" />
        <AlertDescription>{{ error }}</AlertDescription>
      </Alert>
      <div>
        <Button as="a" :href="connectUrl" variant="outline" class="gap-2.5">
          <GoogleMark class="size-[1.15em]" />
          Connect Google Business Profile
        </Button>
      </div>
      <p class="text-xs text-muted-foreground">
        This is a separate permission from signing in, and only reads your business
        listings. Disconnect it at any time from Settings.
      </p>
    </div>
  </div>
</template>
