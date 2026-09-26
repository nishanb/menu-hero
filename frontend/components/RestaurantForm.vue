<script setup lang="ts">
/**
 * The restaurant profile, as a form. One component for both places it is needed:
 * onboarding (`create` mode, empty) and settings (`edit` mode, prefilled).
 *
 * It owns no persistence. `submit` hands the parent exactly the fields that changed, and
 * the parent decides whether that is a `POST` or a `PATCH` — which keeps this file about
 * the form and nothing else.
 *
 * The chips for services and diet options come from `GET /api/v1/tenants/options` and are
 * suggestions, not a closed set: both fields accept anything typed in, because a kitchen
 * that caters for something the list has never heard of must still be able to say so.
 */
import type { Restaurant, RestaurantCreate } from '~/types/api'

const props = withDefaults(
  defineProps<{
    /** The restaurant being edited, or `undefined` when creating one. */
    restaurant?: Restaurant
    mode?: 'create' | 'edit'
    submitLabel?: string
    busy?: boolean
  }>(),
  { mode: 'create', submitLabel: 'Save', busy: false },
)

const emit = defineEmits<{
  submit: [changes: RestaurantCreate]
  cancel: []
}>()

const api = useRestaurantApi()

/** Chips, fetched once. A failure is not worth a message: the fields still work. */
const { data: options } = await useAsyncData('restaurant-options', () => api.options(), {
  default: () => ({ services: [], diet_options: [] }),
})

const name = ref(props.restaurant?.name ?? '')
const description = ref(props.restaurant?.description ?? '')
const locationUrl = ref(props.restaurant?.location_url ?? '')
const logo = ref(props.restaurant?.logo ?? '')
const services = ref<string[]>([...(props.restaurant?.services ?? [])])
const dietOptions = ref<string[]>([...(props.restaurant?.diet_options ?? [])])

/** `extras` is a map in the API and a list here: a map has no stable order to render. */
interface ExtraRow { key: string, value: string }
const extras = ref<ExtraRow[]>(
  Object.entries(props.restaurant?.extras ?? {}).map(([key, value]) => ({ key, value })),
)

/**
 * Prefilled rows, not placeholder text: an operator has to keep these on file, and an
 * empty form gives no hint that this is where they go. Removing a row is one click.
 */
const SUGGESTED_EXTRAS = ['fssai_licence', 'gst_number'] as const

if (props.mode === 'create' && extras.value.length === 0) {
  extras.value = SUGGESTED_EXTRAS.map(key => ({ key, value: '' }))
}

/** `fssai_licence` -> `Fssai licence`, so the stored key is still recognisable as a label. */
function humanise(key: string): string {
  const words = key.replace(/[_-]+/g, ' ').trim()
  return words.charAt(0).toUpperCase() + words.slice(1)
}

const nameError = computed(() => (name.value.trim() ? '' : 'A name is needed'))
const slugPreview = computed(() => slugify(name.value))

const locationError = computed(() =>
  !locationUrl.value.trim() || locationUrl.value.trim().startsWith('https://')
    ? ''
    : 'Paste the https:// link from Google Maps',
)

const canSubmit = computed(() => !nameError.value && !locationError.value && !props.busy)

/** Free-text additions to the open lists, so the chips never become a ceiling. */
const newService = ref('')
const newDiet = ref('')

/**
 * Both lists behave identically, but the handlers are per-field rather than generic: refs
 * are auto-unwrapped in a template, so a `(list: Ref<string[]>) => …` helper can only be
 * called from script, never from an `@toggle`.
 */
function toggle(list: string[], option: string): string[] {
  return list.includes(option) ? list.filter(item => item !== option) : [...list, option]
}

function added(list: string[], text: string): string[] {
  const option = text.trim().toLowerCase()
  return option && !list.includes(option) ? [...list, option] : list
}

function toggleService(option: string): void {
  services.value = toggle(services.value, option)
}

function toggleDiet(option: string): void {
  dietOptions.value = toggle(dietOptions.value, option)
}

function addService(): void {
  services.value = added(services.value, newService.value)
  newService.value = ''
}

function addDiet(): void {
  dietOptions.value = added(dietOptions.value, newDiet.value)
  newDiet.value = ''
}

/* --- logo -------------------------------------------------------------------
 * Stored inline as a base64 data URL, so there is no object store to stand up for
 * something that is one small image per restaurant. The backend caps it at ~375 KB and
 * accepts PNG, JPEG and WEBP only (an SVG can carry script), so both are checked here too
 * — a rejection after the upload round trip is a worse way to learn the same thing.
 */
const LOGO_TYPES = ['image/png', 'image/jpeg', 'image/webp']
const MAX_LOGO_BYTES = 350_000
const logoError = ref('')
const logoInput = ref<HTMLInputElement | null>(null)

function onLogoPicked(event: Event): void {
  const file = (event.target as HTMLInputElement).files?.[0]
  if (!file) {
    return
  }
  logoError.value = ''
  if (!LOGO_TYPES.includes(file.type)) {
    logoError.value = 'Choose a PNG, JPEG or WEBP image'
    return
  }
  if (file.size > MAX_LOGO_BYTES) {
    logoError.value = 'That image is over 350 KB — use a smaller one'
    return
  }
  const reader = new FileReader()
  reader.onload = () => {
    logo.value = typeof reader.result === 'string' ? reader.result : ''
  }
  reader.onerror = () => {
    logoError.value = 'That file could not be read'
  }
  reader.readAsDataURL(file)
}

function clearLogo(): void {
  logo.value = ''
  logoError.value = ''
  if (logoInput.value) {
    logoInput.value.value = ''
  }
}

/** Everything the form holds, in the shape the API takes. */
function collect(): RestaurantCreate {
  return {
    name: name.value.trim(),
    description: description.value.trim(),
    location_url: locationUrl.value.trim(),
    logo: logo.value,
    services: services.value,
    diet_options: dietOptions.value,
    extras: Object.fromEntries(
      extras.value
        .filter(row => row.key.trim() && row.value.trim())
        .map(row => [row.key.trim(), row.value.trim()]),
    ),
  }
}

function onSubmit(): void {
  if (canSubmit.value) {
    emit('submit', collect())
  }
}
</script>

<template>
  <form class="grid gap-8" @submit.prevent="onSubmit">
    <!-- Identity ------------------------------------------------------------ -->
    <section class="grid gap-4">
      <div class="grid gap-2">
        <Label for="restaurant-name">Name</Label>
        <Input
          id="restaurant-name"
          v-model="name"
          placeholder="Spice Garden"
          autocomplete="organization"
          maxlength="200"
          required
        />
        <p class="min-h-4 text-xs text-muted-foreground">
          <template v-if="mode === 'edit' && restaurant">
            Address: <span class="font-mono">{{ restaurant.slug }}</span> — fixed once created
          </template>
          <template v-else-if="slugPreview">
            Address: <span class="font-mono">{{ slugPreview }}</span>
          </template>
        </p>
      </div>

      <div class="grid gap-2">
        <Label for="restaurant-description">Description</Label>
        <Textarea
          id="restaurant-description"
          v-model="description"
          rows="3"
          maxlength="2000"
          placeholder="Coastal Karnataka home cooking, open since 1984."
        />
        <p class="text-xs text-muted-foreground">
          A couple of sentences about the place. The assistant uses this when it talks to
          your diners.
        </p>
      </div>

      <div class="grid gap-2">
        <Label for="restaurant-location">Google Maps link</Label>
        <Input
          id="restaurant-location"
          v-model="locationUrl"
          type="url"
          inputmode="url"
          placeholder="https://maps.app.goo.gl/…"
          maxlength="2000"
          :aria-invalid="Boolean(locationError)"
        />
        <p class="min-h-4 text-xs" :class="locationError ? 'text-destructive' : 'text-muted-foreground'">
          {{ locationError || 'Share the place in Google Maps and paste the link.' }}
        </p>
      </div>
    </section>

    <Separator />

    <!-- Logo ---------------------------------------------------------------- -->
    <section class="grid gap-3">
      <div>
        <h3 class="text-sm font-medium">Logo</h3>
        <p class="mt-0.5 text-xs text-muted-foreground">PNG, JPEG or WEBP, up to 350 KB.</p>
      </div>
      <div class="flex items-center gap-4">
        <span class="grid size-16 shrink-0 place-items-center overflow-hidden rounded-xl border border-border bg-muted">
          <img v-if="logo" :src="logo" alt="" class="size-full object-cover">
          <FontAwesomeIcon v-else :icon="['fas', 'image']" class="text-muted-foreground" />
        </span>
        <div class="flex flex-wrap items-center gap-2">
          <Button type="button" variant="outline" size="sm" @click="logoInput?.click()">
            {{ logo ? 'Replace' : 'Choose image' }}
          </Button>
          <Button v-if="logo" type="button" variant="ghost" size="sm" @click="clearLogo">
            Remove
          </Button>
          <input
            ref="logoInput"
            type="file"
            accept="image/png,image/jpeg,image/webp"
            class="sr-only"
            @change="onLogoPicked"
          >
        </div>
      </div>
      <p v-if="logoError" class="text-xs text-destructive">{{ logoError }}</p>
    </section>

    <Separator />

    <!-- How it trades -------------------------------------------------------- -->
    <section class="grid gap-6">
      <div class="grid gap-3">
        <div>
          <h3 class="text-sm font-medium">Services</h3>
          <p class="mt-0.5 text-xs text-muted-foreground">How people get their food.</p>
        </div>
        <OptionChips
          :model-value="services"
          :suggestions="options.services"
          name="service"
          @toggle="toggleService"
        />
        <div class="flex gap-2">
          <Input
            v-model="newService"
            placeholder="Add another — catering, events…"
            maxlength="40"
            class="max-w-xs"
            @keydown.enter.prevent="addService"
          />
          <Button
            type="button"
            variant="outline"
            :disabled="!newService.trim()"
            @click="addService"
          >
            Add
          </Button>
        </div>
      </div>

      <div class="grid gap-3">
        <div>
          <h3 class="text-sm font-medium">Diet options</h3>
          <p class="mt-0.5 text-xs text-muted-foreground">
            What the kitchen caters for. Add your own if it is not here.
          </p>
        </div>
        <OptionChips
          :model-value="dietOptions"
          :suggestions="options.diet_options"
          name="diet"
          @toggle="toggleDiet"
        />
        <div class="flex gap-2">
          <Input
            v-model="newDiet"
            placeholder="Add another — pescatarian, gluten-free…"
            maxlength="40"
            class="max-w-xs"
            @keydown.enter.prevent="addDiet"
          />
          <Button
            type="button"
            variant="outline"
            :disabled="!newDiet.trim()"
            @click="addDiet"
          >
            Add
          </Button>
        </div>
      </div>
    </section>

    <Separator />

    <!-- Licences and anything else ------------------------------------------ -->
    <section class="grid gap-3">
      <div>
        <h3 class="text-sm font-medium">Additional information</h3>
        <p class="mt-0.5 text-xs text-muted-foreground">
          Licence and tax numbers, and anything else worth keeping on file. Blank rows are
          ignored.
        </p>
      </div>

      <div class="grid gap-2">
        <div v-for="(row, index) in extras" :key="index" class="flex flex-wrap items-center gap-2">
          <Input
            v-model="row.key"
            :aria-label="`Property ${index + 1} name`"
            :placeholder="humanise('property_name')"
            maxlength="40"
            class="w-full sm:w-52"
          />
          <Input
            v-model="row.value"
            :aria-label="`${humanise(row.key) || 'Property'} value`"
            placeholder="Value"
            maxlength="200"
            class="w-full flex-1 sm:w-auto"
          />
          <Button
            type="button"
            variant="ghost"
            size="icon"
            :aria-label="`Remove ${humanise(row.key) || 'this property'}`"
            @click="extras.splice(index, 1)"
          >
            <FontAwesomeIcon :icon="['fas', 'xmark']" />
          </Button>
        </div>
      </div>

      <div>
        <Button type="button" variant="outline" size="sm" @click="extras.push({ key: '', value: '' })">
          <FontAwesomeIcon :icon="['fas', 'plus']" />
          Add a property
        </Button>
      </div>
    </section>

    <!-- Actions -------------------------------------------------------------- -->
    <div class="flex flex-wrap items-center gap-3 border-t border-border pt-6">
      <Button type="submit" :disabled="!canSubmit">
        <FontAwesomeIcon
          v-if="busy"
          :icon="['fas', 'spinner']"
          class="motion-safe:animate-spin"
        />
        {{ submitLabel }}
      </Button>
      <Button type="button" variant="ghost" :disabled="busy" @click="emit('cancel')">
        Cancel
      </Button>
      <p v-if="nameError" class="text-xs text-muted-foreground">{{ nameError }}</p>
    </div>
  </form>
</template>
