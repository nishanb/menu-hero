<script setup lang="ts">
/**
 * Where an invitation link lands: `/invite?token=…`.
 *
 * The backend has generated this URL since invites existed, and `middleware/auth.global.ts`
 * already lists `/invite` as public — the page was the missing half.
 *
 * Public because the invitee usually arrives signed out, and signing in *is* the accept:
 * the Google callback consumes every pending invite for the address it just verified. So
 * there are two paths, and only one of them posts a token:
 *
 *   signed out  ->  "Continue with Google" with `next=/invite?token=…`, and the callback
 *                   applies the invitation on the way through.
 *   signed in   ->  `POST /api/v1/auth/invites/accept`, which is the case the token is for.
 *
 * Either way the *server* creates the membership after checking the verified email matches,
 * so holding the link grants nothing to whoever opens it.
 */
import { HOME_PATH, fetchSession } from '~/composables/useSession'
import { toApiError } from '~/utils/api-error'

const route = useRoute()
const api = useRestaurantApi()
const { isAuthenticated, user } = useSession()

const token = computed(() => (typeof route.query.token === 'string' ? route.query.token : ''))

/** Round-trip back here after signing in, so the invitation is applied then. */
const signInUrl = computed(
  () => `/api/v1/auth/google?next=${encodeURIComponent(route.fullPath)}`,
)

const accepting = ref(false)
const leaving = ref(false)
const error = ref('')
const accepted = ref(false)

/**
 * A person who signed in *from* this link has already had it applied by the callback, so
 * there is nothing to post and the token is spent. Say so rather than showing them a
 * button that would answer 400.
 */
const alreadyApplied = ref(false)

async function accept(): Promise<void> {
  if (!token.value) {
    return
  }
  accepting.value = true
  error.value = ''
  try {
    await api.acceptInvite(token.value)
    await fetchSession(true)
    accepted.value = true
  }
  catch (cause) {
    const failure = toApiError(cause)
    // 400 covers spent, expired and wrong-address alike. The first of those is the
    // ordinary outcome of arriving here straight after signing in from the link.
    if (failure.status === 400) {
      alreadyApplied.value = true
    }
    else {
      error.value = failure.detail
    }
  }
  finally {
    accepting.value = false
  }
}

definePageMeta({ layout: 'auth' })

useHead({ title: 'Your invitation' })
</script>

<template>
  <div class="flex min-h-dvh items-center justify-center bg-background px-5 py-16">
    <div class="w-full max-w-md">
      <div class="mb-8 inline-flex items-center gap-2.5">
        <span class="grid size-8 place-items-center rounded-[9px] bg-white shadow-sm ring-1 ring-black/5">
          <img src="/brand-mark.png" alt="" width="17" height="20" class="h-5 w-auto">
        </span>
        <span class="text-[0.95rem] font-semibold tracking-tight">MenuHero</span>
      </div>

      <!-- No token: the link was truncated somewhere between there and here. -->
      <section v-if="!token" class="rounded-xl border border-border bg-card p-6">
        <h1 class="text-xl font-normal tracking-[-0.02em]">That invitation link is incomplete</h1>
        <p class="mt-2 text-sm leading-relaxed text-muted-foreground">
          Ask whoever invited you to send it again — the whole link, including everything
          after the question mark.
        </p>
      </section>

      <!-- Done. -->
      <section v-else-if="accepted" class="rounded-xl border border-border bg-card p-6">
        <span class="grid size-10 place-items-center rounded-full bg-primary/10 text-primary">
          <FontAwesomeIcon :icon="['fas', 'check']" />
        </span>
        <h1 class="mt-4 text-xl font-normal tracking-[-0.02em]">You are in</h1>
        <p class="mt-2 text-sm leading-relaxed text-muted-foreground">
          The restaurant is in your switcher now.
        </p>
        <Button class="mt-6" as-child>
          <NuxtLink :to="HOME_PATH">
            Go to the dashboard
            <FontAwesomeIcon :icon="['fas', 'arrow-right']" />
          </NuxtLink>
        </Button>
      </section>

      <!-- Signed in: post the token. -->
      <section v-else-if="isAuthenticated" class="rounded-xl border border-border bg-card p-6">
        <h1 class="text-xl font-normal tracking-[-0.02em]">You have been invited</h1>
        <p class="mt-2 text-sm leading-relaxed text-muted-foreground">
          Accepting adds this restaurant to
          <span class="text-foreground">{{ user?.email }}</span>. An invitation only applies
          to the address it was sent to.
        </p>

        <Alert v-if="alreadyApplied" class="mt-5">
          <FontAwesomeIcon :icon="['fas', 'circle-info']" />
          <AlertTitle>Nothing left to accept</AlertTitle>
          <AlertDescription>
            This invitation has already been used, has expired, or was sent to a different
            address. If you signed in from the link just now, it was applied then — check
            the restaurant switcher.
          </AlertDescription>
        </Alert>

        <Alert v-else-if="error" variant="destructive" class="mt-5">
          <FontAwesomeIcon :icon="['fas', 'circle-exclamation']" />
          <AlertTitle>That did not go through</AlertTitle>
          <AlertDescription>{{ error }}</AlertDescription>
        </Alert>

        <div class="mt-6 flex flex-wrap gap-3">
          <Button v-if="!alreadyApplied" :disabled="accepting" @click="accept">
            <FontAwesomeIcon
              v-if="accepting"
              :icon="['fas', 'spinner']"
              class="motion-safe:animate-spin"
            />
            Accept invitation
          </Button>
          <Button variant="ghost" as-child>
            <NuxtLink :to="HOME_PATH">Go to the dashboard</NuxtLink>
          </Button>
        </div>
      </section>

      <!-- Signed out: signing in is the accept. -->
      <section v-else class="rounded-xl border border-border bg-card p-6">
        <h1 class="text-xl font-normal tracking-[-0.02em]">You have been invited</h1>
        <p class="mt-2 text-sm leading-relaxed text-muted-foreground">
          Sign in with the Google account the invitation was sent to. The restaurant is
          added as you sign in — there is nothing else to accept.
        </p>
        <Button
          as="a"
          :href="signInUrl"
          variant="outline"
          class="mt-6 h-11 w-full justify-center gap-2.5"
          @click="leaving = true"
        >
          <FontAwesomeIcon
            v-if="leaving"
            :icon="['fas', 'spinner']"
            class="size-[1.05em] motion-safe:animate-spin"
          />
          <GoogleMark v-else class="size-[1.15em]" />
          {{ leaving ? 'Taking you to Google' : 'Continue with Google' }}
        </Button>
      </section>
    </div>
  </div>
</template>
