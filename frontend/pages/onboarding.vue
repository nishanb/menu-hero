<script setup lang="ts">
/**
 * Setting up a restaurant — its own section of the app, not a dialog.
 *
 * A dialog was the wrong shape for this: the form is long, an import is a round trip out
 * to Google and back, and the person is deciding something they will live with. A page can
 * be linked to, returned to after consent, and reloaded without losing the thread.
 *
 * Two ways in, side by side and equal:
 *
 *   Import from Google Business  ->  a restaurant, prefilled, in one click
 *   Set it up manually           ->  the same form, empty
 *
 * The Google half hides itself on an installation that cannot do it (no OAuth client, or
 * no `SECRET_KEY` to encrypt the connection with), so that case just sees a form.
 */
import type { Restaurant, RestaurantCreate } from '~/types/api'
import { HOME_PATH, fetchSession } from '~/composables/useSession'
import { toApiError } from '~/utils/api-error'

const api = useRestaurantApi()
const { hasRestaurants, upsert, refresh } = useRestaurants()

const ONBOARDING_PATH = '/onboarding'

/**
 * `manual` once they choose the form, so the import panel does not sit above a long form
 * they have already decided against. `choose` is the fork.
 */
const step = ref<'choose' | 'manual'>('choose')
const saving = ref(false)
const error = ref('')

/** Freshly created, so the page can confirm rather than vanish. */
const created = ref<Restaurant | null>(null)

async function onSubmit(changes: RestaurantCreate): Promise<void> {
  saving.value = true
  error.value = ''
  try {
    await finish(await api.create(changes))
  }
  catch (cause) {
    error.value = toApiError(cause).detail
  }
  finally {
    saving.value = false
  }
}

/**
 * Fold the new restaurant in and re-read the session.
 *
 * The session is what carries the memberships and `active_tenant_id`, and the person has
 * just gone from belonging to nothing to owning a restaurant — without the re-read the rail
 * and the dashboard would still describe them as belonging to nowhere.
 */
async function finish(restaurant: Restaurant): Promise<void> {
  created.value = restaurant
  upsert(restaurant, { activate: true })
  await fetchSession(true)
  await refresh()
}

function goToRestaurant(): void {
  navigateTo(HOME_PATH)
}

definePageMeta({ layout: 'app' })

useHead({ title: 'Set up your restaurant' })
</script>

<template>
  <div class="mx-auto w-full max-w-2xl px-5 pt-[6vh] pb-20">
    <!-- Done ----------------------------------------------------------------- -->
    <section v-if="created" class="rounded-xl border border-border bg-card p-6 shadow-xs">
      <span class="grid size-10 place-items-center rounded-full bg-primary/10 text-primary">
        <FontAwesomeIcon :icon="['fas', 'check']" />
      </span>
      <h1 class="mt-4 text-[1.6rem] leading-tight font-normal tracking-[-0.02em]">
        {{ created.name }} is set up.
      </h1>
      <p class="mt-2 text-sm leading-relaxed text-muted-foreground">
        You are its owner. Invite the rest of your team from Settings whenever you are
        ready — an invitation is applied the moment they sign in with that address.
      </p>
      <div class="mt-6 flex flex-wrap gap-3">
        <Button @click="goToRestaurant">
          Go to the dashboard
          <FontAwesomeIcon :icon="['fas', 'arrow-right']" />
        </Button>
        <Button variant="outline" as-child>
          <NuxtLink to="/settings?tab=team">Invite your team</NuxtLink>
        </Button>
        <Button variant="ghost" @click="created = null; step = 'choose'">
          Add another restaurant
        </Button>
      </div>
    </section>

    <template v-else>
      <header>
        <h1 class="text-[1.75rem] leading-tight font-normal tracking-[-0.02em]">
          {{ hasRestaurants ? 'Add a restaurant' : 'Set up your restaurant' }}
        </h1>
        <p class="mt-2 text-sm leading-relaxed text-muted-foreground">
          <template v-if="hasRestaurants">
            A second restaurant gets its own menus, team and orders. You will own it.
          </template>
          <template v-else>
            This is the one thing to do before anything else works. It takes a minute, and
            everything here can be changed later.
          </template>
        </p>
      </header>

      <Alert v-if="error" variant="destructive" class="mt-6">
        <FontAwesomeIcon :icon="['fas', 'circle-exclamation']" />
        <AlertTitle>That could not be saved</AlertTitle>
        <AlertDescription>{{ error }}</AlertDescription>
      </Alert>

      <!-- The fork ----------------------------------------------------------- -->
      <div v-if="step === 'choose'" class="mt-8 grid gap-6">
        <GoogleBusinessImport :return-path="ONBOARDING_PATH" @imported="finish" />

        <div class="flex items-center gap-4">
          <Separator class="flex-1" />
          <span class="text-xs tracking-[0.12em] text-muted-foreground uppercase">or</span>
          <Separator class="flex-1" />
        </div>

        <button
          type="button"
          class="flex items-center gap-4 rounded-xl border border-border bg-card p-5 text-left transition-colors outline-hidden hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring"
          @click="step = 'manual'"
        >
          <span class="grid size-10 shrink-0 place-items-center rounded-lg bg-muted">
            <FontAwesomeIcon :icon="['fas', 'utensils']" class="text-muted-foreground" />
          </span>
          <span class="min-w-0 flex-1">
            <span class="block font-medium">Set it up manually</span>
            <span class="mt-0.5 block text-sm text-muted-foreground">
              Name, description, services and licence numbers. Two minutes.
            </span>
          </span>
          <FontAwesomeIcon :icon="['fas', 'chevron-right']" class="shrink-0 text-muted-foreground" />
        </button>
      </div>

      <!-- The form ------------------------------------------------------------ -->
      <div v-else class="mt-8">
        <RestaurantForm
          mode="create"
          submit-label="Create restaurant"
          :busy="saving"
          @submit="onSubmit"
          @cancel="step = 'choose'"
        />
      </div>
    </template>
  </div>
</template>
