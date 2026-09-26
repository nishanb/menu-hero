<script setup lang="ts">
/**
 * The team of one restaurant: who is in it, and who has been invited.
 *
 * This is where invitations live now — Settings, next to the people they concern, rather
 * than in the restaurant switcher. Owners and platform admins can change things here;
 * staff see the list and nothing else. The greying-out is a courtesy: the boundary that
 * actually holds is `assert_can_manage_tenant` on the backend, which answers 403 whatever
 * this component renders.
 *
 * Nothing is emailed yet, so a new invitation returns a one-time link that has to be sent
 * on manually. It is shown once — the backend stores only a digest — which is why it is
 * copied from a panel rather than listed with the others.
 */
import type { Invite, Member, TenantRole } from '~/types/api'
import { toApiError } from '~/utils/api-error'

const props = defineProps<{
  tenantId: string
  /** Whether to offer the actions at all. */
  canManage: boolean
}>()

const api = useRestaurantApi()
const { user } = useSession()

const members = ref<Member[]>([])
const invites = ref<Invite[]>([])
const loading = ref(true)
const error = ref('')

const inviteEmail = ref('')
const inviteRole = ref<TenantRole>('staff')
const inviting = ref(false)
const busyId = ref('')

/**
 * Removal is confirmed, the two role changes are not: taking someone off a restaurant can
 * only be undone by inviting them back and waiting for them to sign in again, which is a
 * different order of mistake from moving an owner to staff.
 *
 * Two refs rather than one. Driving the dialog's `open` off `removing` alone looks tidier
 * but silently does nothing: reka-ui closes the dialog on the confirm click, that close
 * clears `removing`, and the handler then reads `null` and returns. Keeping the payload
 * independent of the open flag means the click always has the person it was about.
 */
const removing = ref<Member | null>(null)
const removalOpen = ref(false)

/** The link from the last invitation, shown once and then dismissed. */
const freshLink = ref<{ email: string, url: string } | null>(null)
const copied = ref(false)

const ROLE_LABELS: Record<TenantRole, string> = { owner: 'Owner', staff: 'Staff' }

const ownerCount = computed(() => members.value.filter(member => member.role === 'owner').length)

/** Fixed locale and UTC: the server and the browser must format these identically. */
const dateFormat = new Intl.DateTimeFormat('en-GB', {
  day: 'numeric',
  month: 'short',
  year: 'numeric',
  timeZone: 'UTC',
})

function formatDate(value: string): string {
  return dateFormat.format(new Date(value))
}

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    members.value = (await api.members(props.tenantId)).members
    // Staff may read the team but not the invitations; a 403 here is expected, not a fault.
    invites.value = props.canManage ? (await api.invites(props.tenantId)).invites : []
  }
  catch (cause) {
    error.value = toApiError(cause).detail
  }
  finally {
    loading.value = false
  }
}

async function sendInvite(): Promise<void> {
  const email = inviteEmail.value.trim()
  if (!email) {
    return
  }
  inviting.value = true
  error.value = ''
  try {
    const created = await api.invite(props.tenantId, email, inviteRole.value)
    freshLink.value = { email: created.invite.email, url: created.accept_url }
    copied.value = false
    inviteEmail.value = ''
    await load()
  }
  catch (cause) {
    error.value = toApiError(cause).detail
  }
  finally {
    inviting.value = false
  }
}

async function copyLink(): Promise<void> {
  if (!freshLink.value) {
    return
  }
  try {
    await navigator.clipboard.writeText(freshLink.value.url)
    copied.value = true
  }
  catch {
    // A denied clipboard permission is not an error worth a banner: the link is on screen
    // and selectable, which is the fallback anyway.
    copied.value = false
  }
}

async function revoke(invite: Invite): Promise<void> {
  busyId.value = invite.id
  error.value = ''
  try {
    await api.revokeInvite(props.tenantId, invite.id)
    await load()
  }
  catch (cause) {
    error.value = toApiError(cause).detail
  }
  finally {
    busyId.value = ''
  }
}

async function changeRole(member: Member, role: TenantRole): Promise<void> {
  busyId.value = member.user.id
  error.value = ''
  try {
    await api.changeRole(props.tenantId, member.user.id, role)
    await load()
  }
  catch (cause) {
    error.value = toApiError(cause).detail
  }
  finally {
    busyId.value = ''
  }
}

function askToRemove(member: Member): void {
  removing.value = member
  removalOpen.value = true
}

async function confirmRemoval(): Promise<void> {
  const member = removing.value
  removalOpen.value = false
  if (!member) {
    return
  }
  busyId.value = member.user.id
  error.value = ''
  try {
    await api.removeMember(props.tenantId, member.user.id)
    await load()
  }
  catch (cause) {
    error.value = toApiError(cause).detail
  }
  finally {
    busyId.value = ''
    removing.value = null
  }
}

/** How to name the person in the confirmation, without repeating the whole row. */
function nameOf(member: Member): string {
  return member.user.name || member.user.email
}

watch(() => props.tenantId, load, { immediate: true })
</script>

<template>
  <div class="grid gap-8">
    <Alert v-if="error" variant="destructive">
      <FontAwesomeIcon :icon="['fas', 'circle-exclamation']" />
      <AlertTitle>That did not go through</AlertTitle>
      <AlertDescription>{{ error }}</AlertDescription>
    </Alert>

    <!-- Invite --------------------------------------------------------------- -->
    <section v-if="canManage" class="grid gap-3">
      <div>
        <h3 class="text-sm font-medium">Invite someone</h3>
        <p class="mt-0.5 text-xs text-muted-foreground">
          They join the moment they sign in with that address — there is nothing for them
          to accept.
        </p>
      </div>

      <form class="flex flex-wrap items-end gap-2" @submit.prevent="sendInvite">
        <div class="grid min-w-56 flex-1 gap-1.5">
          <Label for="invite-email" class="sr-only">Email address</Label>
          <Input
            id="invite-email"
            v-model="inviteEmail"
            type="email"
            required
            placeholder="server@example.com"
            autocomplete="email"
          />
        </div>
        <div class="grid gap-1.5">
          <Label for="invite-role" class="sr-only">Role</Label>
          <Select v-model="inviteRole">
            <SelectTrigger id="invite-role" class="w-36">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="staff">Staff</SelectItem>
              <SelectItem value="owner">Owner</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <Button type="submit" :disabled="inviting || !inviteEmail.trim()">
          <FontAwesomeIcon
            v-if="inviting"
            :icon="['fas', 'spinner']"
            class="motion-safe:animate-spin"
          />
          Send invite
        </Button>
      </form>

      <!-- The link, once. -->
      <div v-if="freshLink" class="grid gap-2 rounded-lg border border-border bg-muted/40 p-4">
        <div class="flex items-start justify-between gap-3">
          <p class="text-sm">
            Send this link to <span class="font-medium">{{ freshLink.email }}</span>. It is
            shown once — we keep only a digest of it.
          </p>
          <Button
            variant="ghost"
            size="icon"
            aria-label="Dismiss the invite link"
            @click="freshLink = null"
          >
            <FontAwesomeIcon :icon="['fas', 'xmark']" />
          </Button>
        </div>
        <div class="flex flex-wrap items-center gap-2">
          <code class="min-w-0 flex-1 truncate rounded bg-background px-2 py-1.5 font-mono text-xs">
            {{ freshLink.url }}
          </code>
          <Button variant="outline" size="sm" @click="copyLink">
            <FontAwesomeIcon :icon="['fas', copied ? 'check' : 'copy']" />
            {{ copied ? 'Copied' : 'Copy' }}
          </Button>
        </div>
      </div>
    </section>

    <!-- Members -------------------------------------------------------------- -->
    <section class="grid gap-3">
      <h3 class="text-sm font-medium">Team</h3>

      <div v-if="loading" class="grid gap-2">
        <Skeleton class="h-12 w-full" />
        <Skeleton class="h-12 w-full" />
      </div>

      <div v-else class="overflow-x-auto rounded-lg border border-border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Person</TableHead>
              <TableHead>Role</TableHead>
              <TableHead>Since</TableHead>
              <TableHead v-if="canManage" class="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableRow v-for="member in members" :key="member.user.id">
              <TableCell>
                <div class="flex items-center gap-2.5">
                  <Avatar class="size-7">
                    <AvatarImage
                      v-if="member.user.picture"
                      :src="member.user.picture"
                      alt=""
                      referrerpolicy="no-referrer"
                    />
                    <AvatarFallback class="text-[0.65rem]">
                      {{ (member.user.name || member.user.email).charAt(0).toUpperCase() }}
                    </AvatarFallback>
                  </Avatar>
                  <div class="min-w-0">
                    <p class="truncate text-sm font-medium">
                      {{ nameOf(member) }}
                      <span v-if="member.user.id === user?.id" class="text-muted-foreground">(you)</span>
                    </p>
                    <p class="truncate text-xs text-muted-foreground">{{ member.user.email }}</p>
                  </div>
                </div>
              </TableCell>
              <TableCell>
                <Badge :variant="member.role === 'owner' ? 'default' : 'secondary'">
                  {{ ROLE_LABELS[member.role] }}
                </Badge>
              </TableCell>
              <TableCell class="text-sm text-muted-foreground">
                {{ formatDate(member.created_at) }}
              </TableCell>
              <TableCell v-if="canManage" class="text-right">
                <DropdownMenu>
                  <DropdownMenuTrigger as-child>
                    <Button
                      variant="ghost"
                      size="icon"
                      :disabled="busyId === member.user.id"
                      :aria-label="`Manage ${nameOf(member)}`"
                    >
                      <FontAwesomeIcon :icon="['fas', 'ellipsis']" />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end" class="w-52">
                    <DropdownMenuItem
                      v-if="member.role === 'staff'"
                      @select="changeRole(member, 'owner')"
                    >
                      Make an owner
                    </DropdownMenuItem>
                    <DropdownMenuItem
                      v-else
                      :disabled="ownerCount <= 1"
                      @select="changeRole(member, 'staff')"
                    >
                      Move to staff
                    </DropdownMenuItem>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem
                      variant="destructive"
                      :disabled="member.role === 'owner' && ownerCount <= 1"
                      @select="askToRemove(member)"
                    >
                      Remove from restaurant
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              </TableCell>
            </TableRow>
            <TableRow v-if="!members.length">
              <TableCell :colspan="canManage ? 4 : 3" class="py-8 text-center text-sm text-muted-foreground">
                Nobody yet.
              </TableCell>
            </TableRow>
          </TableBody>
        </Table>
      </div>

      <p v-if="canManage && ownerCount <= 1" class="text-xs text-muted-foreground">
        A restaurant always keeps at least one owner, so the last one cannot be moved to
        staff or removed.
      </p>
    </section>

    <!-- Pending invitations --------------------------------------------------- -->
    <section v-if="canManage" class="grid gap-3">
      <div>
        <h3 class="text-sm font-medium">Pending invitations</h3>
        <p class="mt-0.5 text-xs text-muted-foreground">
          Revoking one stops its link working immediately.
        </p>
      </div>

      <div v-if="loading" class="grid gap-2">
        <Skeleton class="h-12 w-full" />
      </div>

      <div v-else-if="invites.length" class="overflow-x-auto rounded-lg border border-border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Email</TableHead>
              <TableHead>Role</TableHead>
              <TableHead>Expires</TableHead>
              <TableHead class="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableRow v-for="invite in invites" :key="invite.id">
              <TableCell class="text-sm">{{ invite.email }}</TableCell>
              <TableCell>
                <Badge variant="secondary">{{ ROLE_LABELS[invite.role] }}</Badge>
              </TableCell>
              <TableCell class="text-sm text-muted-foreground">
                {{ formatDate(invite.expires_at) }}
              </TableCell>
              <TableCell class="text-right">
                <Button
                  variant="ghost"
                  size="sm"
                  :disabled="busyId === invite.id"
                  @click="revoke(invite)"
                >
                  Revoke
                </Button>
              </TableCell>
            </TableRow>
          </TableBody>
        </Table>
      </div>

      <p v-else class="rounded-lg border border-dashed border-border px-4 py-8 text-center text-sm text-muted-foreground">
        No invitations outstanding.
      </p>
    </section>

    <!-- `ClientOnly`: the dialog root renders no DOM on the server but a portal anchor in
         the browser, so it hydrates as a node mismatch otherwise. Nothing is lost — it can
         only open in response to a click. -->
    <ClientOnly>
      <AlertDialog v-model:open="removalOpen">
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              Remove {{ removing ? nameOf(removing) : '' }}?
            </AlertDialogTitle>
            <AlertDialogDescription>
              They keep their account and lose access to this restaurant. To undo it you
              would have to invite them again and wait for them to sign in.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel @click="removing = null">Keep them</AlertDialogCancel>
            <AlertDialogAction variant="destructive" @click="confirmRemoval">
              Remove
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </ClientOnly>
  </div>
</template>
