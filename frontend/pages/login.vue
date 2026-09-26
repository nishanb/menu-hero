<script setup lang="ts">
/**
 * Sign-in. One action: hand the browser to the backend, which redirects to Google.
 *
 * `GET /api/v1/auth/google` answers 307 to accounts.google.com, so this MUST be a real
 * browser navigation — a `$fetch` would try to follow that cross-origin redirect itself
 * and die on CORS. Hence a plain `<a href>`, not the `$api` plugin.
 *
 * The backend sends every failed sign-in back here as `/login?error=<code>`; the codes
 * come from `backend/app/api/routes/auth.py` and `AuthError.code`.
 */
const route = useRoute()

const SIGN_IN_URL = '/api/v1/auth/google'

/** What went wrong, and what the person can do about it. */
const ERROR_MESSAGES: Record<string, string> = {
  google_declined: 'Google sign-in was cancelled. Start again when you are ready.',
  missing_code: 'That sign-in link is incomplete. Start again from this page.',
  missing_state: 'That sign-in started in another browser. Start again from this page.',
  invalid_state: 'That sign-in link has expired. Start again from this page.',
  google_rejected:
    'Google could not confirm that account. Check you picked the right one, and that its email address is verified.',
  account_disabled: 'This account is switched off. Ask an owner or an admin to turn it back on.',
  account_conflict:
    'That email address is already linked to a different Google account. Sign in with the original account, or ask an admin.',
}

const FALLBACK_MESSAGE = 'Sign-in did not finish. Start again from this page.'

const errorMessage = computed(() => {
  const raw = route.query.error
  if (typeof raw !== 'string' || !raw) {
    return ''
  }
  return ERROR_MESSAGES[raw] ?? FALLBACK_MESSAGE
})

/** Where to land after signing in, when the user was sent here from a deeper page. */
const nextPath = computed(() => {
  const raw = route.query.next
  return typeof raw === 'string' && raw.startsWith('/') && !raw.startsWith('//') ? raw : ''
})

const signInUrl = computed(() =>
  nextPath.value ? `${SIGN_IN_URL}?next=${encodeURIComponent(nextPath.value)}` : SIGN_IN_URL,
)

// The navigation leaves the app, so the button has to say it is working; without this the
// page looks frozen for however long Google takes to answer.
const leaving = ref(false)

definePageMeta({ layout: 'auth' })

useHead({
  title: 'Sign in',
  meta: [{ name: 'description', content: 'Sign in to Menu Hero with your Google account.' }],
})
</script>

<template>
  <!-- `dark` is pinned on: this screen is dark whatever the rest of the app is set to, so
       every shadcn component below resolves its dark tokens rather than the viewer's
       theme. Only the page's own near-black is stated explicitly. `color-scheme` goes with
       it, or a viewer whose app theme is light gets pale scrollbars on a near-black page. -->
  <div class="dark flex min-h-dvh flex-col bg-[#100f0a] text-[#ededea] [color-scheme:dark]">
    <!-- Header and content share one centred column, so the wordmark and the headline sit
         on the same left edge at every width instead of the block stranding at the far
         left of a wide monitor. -->
    <header class="mx-auto w-full max-w-3xl px-6 pt-7 sm:px-10 sm:pt-9">
      <!-- Not a link: `/` sends a signed-out visitor straight back here, so the wordmark
           would only ever reload the page it is already on. -->
      <div class="inline-flex items-center gap-2.5">
        <!-- The brand mark sits on a white tile, as it does on the marketing site: the
             logo's own navy would disappear into this page's near-black. -->
        <span class="grid size-8 place-items-center rounded-[9px] bg-white shadow-sm">
          <img src="/brand-mark.png" alt="" width="17" height="20" class="h-5 w-auto">
        </span>
        <span class="text-[0.95rem] font-semibold tracking-tight">MenuHero</span>
      </div>
    </header>

    <main class="mx-auto flex w-full max-w-3xl flex-1 items-center px-6 pb-24 sm:px-10">
      <div class="w-full max-w-2xl">
        <h1 class="text-[2.1rem] leading-[1.18] font-normal tracking-[-0.02em] sm:text-[2.5rem]">
          Welcome to MenuHero
          <span class="block text-[#6d6a62]">Menus, orders and the kitchen.</span>
        </h1>

        <Alert v-if="errorMessage" variant="destructive" class="mt-10">
          <FontAwesomeIcon :icon="['fas', 'circle-exclamation']" />
          <AlertTitle>Sign-in stopped</AlertTitle>
          <AlertDescription>{{ errorMessage }}</AlertDescription>
        </Alert>

        <Button
          as="a"
          :href="signInUrl"
          variant="outline"
          class="mt-11 h-12 w-full justify-center gap-2.5 rounded-lg border-[#2c2a22] bg-[#16150f] text-[0.95rem] font-normal text-[#ededea] hover:border-[#3a372d] hover:bg-[#1e1c14] hover:text-[#ededea]"
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

        <p class="mt-5 text-sm leading-relaxed text-[#6d6a62]">
          Signing in creates your account. An owner invites you to their restaurant from
          there.
        </p>
      </div>
    </main>
  </div>
</template>
