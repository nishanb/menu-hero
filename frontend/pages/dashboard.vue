<script setup lang="ts">
/**
 * Where every signed-in person lands.
 *
 * The session is already in state by the time this renders — `middleware/auth.global.ts`
 * fetched it and would have redirected had nobody been signed in — so there is no loading
 * state here and no second request.
 *
 * Someone who belongs to no restaurant gets the set-up card instead of the profile panel.
 * It is an offer, not a redirect: an invited server signing in for the first time also has
 * no restaurant, and pushing them into creating one would be exactly wrong.
 *
 * It is deliberately one page for all four roles. The backend still hands out a per-role
 * `portal_path` (`/admin`, `/owner`, `/staff`, `/app`) and `nuxt.config.ts` redirects all of
 * them here; when real portals exist, those route rules are the only thing that changes.
 */
const { user, role, memberships } = useSession()
const { active, hasRestaurants, hasLoaded, canManageActive } = useRestaurants()

const ROLE_COPY: Record<string, { label: string, blurb: string }> = {
  admin: {
    label: 'Platform admin',
    blurb: 'You can change anyone’s role and see every restaurant on the platform.',
  },
  owner: {
    label: 'Owner',
    blurb: 'You run the restaurants in the switcher: menus, staff and invitations are yours.',
  },
  staff: {
    label: 'Staff',
    blurb: 'You work the restaurants in the switcher — menus and orders, not billing or invites.',
  },
  user: {
    label: 'Member',
    blurb: 'Your account is ready. Set up your restaurant, or wait to be invited to one.',
  },
}

const roleCopy = computed(() => (role.value ? ROLE_COPY[role.value] : undefined))

const firstName = computed(() => user.value?.name?.split(' ')[0] || 'there')

// Fixed locale and UTC: the server and the browser must format this identically, or
// hydration replaces the text and Vue warns about the mismatch.
const dateFormat = new Intl.DateTimeFormat('en-GB', {
  day: 'numeric',
  month: 'long',
  year: 'numeric',
  timeZone: 'UTC',
})

const joinedOn = computed(() =>
  user.value ? dateFormat.format(new Date(user.value.created_at)) : '',
)

definePageMeta({ layout: 'app' })

useHead({ title: 'Dashboard' })
</script>

<template>
  <!-- One panel on an otherwise empty canvas, sitting high rather than centred: there is a
       single thing to read here, and more will be stacked under it, not around it. -->
  <div v-if="user" class="mx-auto w-full max-w-xl px-5 pt-[7vh] pb-16">
    <!-- Still finding out. A platform admin holds no memberships, so the session alone
         cannot say whether they have restaurants; offering to set one up and then replacing
         it a moment later is worse than a beat of nothing. -->
    <div v-if="!hasRestaurants && !hasLoaded" class="grid gap-4">
      <Skeleton class="h-40 w-full rounded-xl" />
    </div>

    <!-- No restaurant: the one thing worth doing, offered rather than forced. -->
    <section
      v-else-if="!hasRestaurants"
      class="rounded-xl border border-border bg-card p-5 shadow-xs sm:p-6"
    >
      <h1 class="text-[1.6rem] leading-tight font-normal tracking-[-0.02em]">
        Hello, {{ firstName }}.
      </h1>
      <p class="mt-2 text-sm leading-relaxed text-muted-foreground">
        Your account is ready. It is not attached to a restaurant yet — set one up and you
        will own it, or wait for an owner to invite
        <span class="text-foreground">{{ user.email }}</span> to theirs. An invitation is
        applied the next time you sign in, with nothing for you to accept.
      </p>
      <div class="mt-6 flex flex-wrap gap-3">
        <Button as-child>
          <NuxtLink to="/onboarding">
            Set up your restaurant
            <FontAwesomeIcon :icon="['fas', 'arrow-right']" />
          </NuxtLink>
        </Button>
      </div>
      <p class="mt-5 border-t border-border pt-4 text-xs text-muted-foreground">
        Already listed on Google? Onboarding can import the name, description and address
        straight from your Business Profile.
      </p>
    </section>

    <template v-else>
      <div
        v-if="!active?.detail?.description"
        class="mx-3 rounded-t-xl border border-b-0 border-border bg-muted/40 px-4 py-2.5 text-center text-sm text-muted-foreground"
      >
        <template v-if="canManageActive">
          <NuxtLink to="/settings" class="underline underline-offset-2">Finish the profile</NuxtLink>
          — a description helps the assistant talk about you
        </template>
        <template v-else>
          {{ active?.name }} has no description yet
        </template>
      </div>

      <section class="rounded-xl border border-border bg-card p-5 shadow-xs sm:p-6">
        <h1 class="text-[1.6rem] leading-tight font-normal tracking-[-0.02em]">
          Hello, {{ firstName }}.
        </h1>
        <p v-if="roleCopy" class="mt-1.5 text-sm leading-relaxed text-muted-foreground">
          {{ roleCopy.blurb }}
        </p>

        <!-- Four facts do not need four cards. -->
        <dl class="mt-6 divide-y divide-border border-t border-border text-sm">
          <div class="flex items-baseline justify-between gap-6 py-2.5">
            <dt class="text-muted-foreground">Restaurant</dt>
            <dd class="text-right font-medium">{{ active?.name }}</dd>
          </div>
          <div class="flex items-baseline justify-between gap-6 py-2.5">
            <dt class="text-muted-foreground">Email</dt>
            <dd class="text-right break-all">{{ user.email }}</dd>
          </div>
          <div class="flex items-baseline justify-between gap-6 py-2.5">
            <dt class="text-muted-foreground">Role</dt>
            <dd class="text-right font-medium">{{ roleCopy?.label ?? role }}</dd>
          </div>
          <div class="flex items-baseline justify-between gap-6 py-2.5">
            <dt class="text-muted-foreground">Joined</dt>
            <dd class="text-right">{{ joinedOn }}</dd>
          </div>
        </dl>

        <div v-if="canManageActive" class="mt-6 flex flex-wrap gap-3">
          <Button variant="outline" size="sm" as-child>
            <NuxtLink to="/settings">Edit the restaurant</NuxtLink>
          </Button>
          <Button variant="outline" size="sm" as-child>
            <NuxtLink to="/settings?tab=team">
              Invite your team
              <span v-if="memberships.length" class="sr-only">for {{ active?.name }}</span>
            </NuxtLink>
          </Button>
        </div>
      </section>
    </template>
  </div>
</template>
