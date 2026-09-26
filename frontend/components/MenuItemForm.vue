<script setup lang="ts">
/**
 * The configuration of one dish: everything the item form collects.
 *
 * Laid out the way a POS lays it out — three columns of related fields, identity first,
 * then money, then how it is sold — because the people filling this in have filled the same
 * form in before and the muscle memory is worth more than a tidier grouping.
 *
 * The multiple-choice fields are chips rather than checkboxes, matching the services and
 * diet chips in `RestaurantForm`. What they offer comes from `GET /menu/options`, which
 * serves the very lists the backend validates against — hard-coding them here is how a form
 * and its validators drift apart.
 *
 * Dietary is single-select even though a POS draws it as checkboxes: a dish is not both veg
 * and non-veg, and the import carries exactly one value per item.
 */
import type { GstType, MenuItem, MenuItemWrite, MenuOptions } from '~/types/api'
import { toApiError } from '~/utils/api-error'

const props = defineProps<{
  /** The dish being edited, or `null` when adding one. */
  item: MenuItem | null
  /** Section names to choose from, in menu order. */
  categories: string[]
  /** Where a new dish lands: the section the person was looking at. */
  defaultCategory?: string
  options: MenuOptions
  /** Whose menu this is; the picture upload needs it. */
  tenantId: string
  busy?: boolean
}>()

const emit = defineEmits<{ submit: [changes: MenuItemWrite], cancel: [] }>()

/** `2026-09-30T00:00:00Z` -> `2026-09-30`, which is what `<input type="date">` wants. */
function asDate(value: string | null | undefined): string {
  return value ? value.slice(0, 10) : ''
}

const form = reactive({
  name: props.item?.name ?? '',
  online_name: props.item?.online_name ?? '',
  description: props.item?.description ?? '',
  category: props.item?.category ?? props.defaultCategory ?? '',
  short_code: props.item?.short_code ?? '',
  short_code_2: props.item?.short_code_2 ?? '',
  hsn_code: props.item?.hsn_code ?? '',
  price: props.item?.price ?? 0,
  packing_charges: props.item?.packing_charges ?? 0,
  profit_margin: props.item?.profit_margin ?? 0,
  weight: props.item?.weight ?? 0,
  weight_unit: props.item?.weight_unit ?? '',
  diet: props.item?.diet ?? '',
  gst_type: (props.item?.gst_type ?? '') as GstType | '',
  order_types: [...(props.item?.order_types ?? [])],
  expose_in: [...(props.item?.expose_in ?? [])],
  allow_decimal_quantity: props.item?.allow_decimal_quantity ?? true,
  manufactured_on: asDate(props.item?.manufactured_on),
  expires_on: asDate(props.item?.expires_on),
  is_available: props.item?.is_available ?? true,
})

const error = ref('')

/* ------------------------------------------------------------------ the picture */

const api = useRestaurantApi()
const imageUrl = ref(props.item?.image_url ?? '')
const uploading = ref(false)
const imageInput = ref<HTMLInputElement | null>(null)

/**
 * Upload first, then keep the URL.
 *
 * The bytes never travel with the item: a 2 MB picture inside a JSON patch would be re-sent
 * every time somebody changed the price. What the form holds is the URL the store handed
 * back, which is also what a CDN will hand back when one exists.
 */
async function onImage(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement
  const chosen = input.files?.[0]
  if (!chosen) {
    return
  }
  uploading.value = true
  error.value = ''
  try {
    imageUrl.value = (await api.uploadMenuImage(props.tenantId, chosen)).url
  }
  catch (cause) {
    error.value = toApiError(cause).detail
  }
  finally {
    uploading.value = false
    // Clearing it means picking the same file again still fires `change`.
    input.value = ''
  }
}

function removeImage(): void {
  imageUrl.value = ''
}

/**
 * How an option value reads on screen.
 *
 * The named ones are here because the generic transform gets them wrong in ways that matter:
 * `non-veg` is a compound, not two words, and "Non veg" on a menu tool reads as a typo.
 */
const LABELS: Record<string, string> = {
  'non-veg': 'Non-veg',
  'dine-in': 'Dine-in',
  'online-orders': 'Online orders',
  'captain-app': 'Captain app',
}

function label(option: string): string {
  const known = LABELS[option]
  if (known) {
    return known
  }
  return option.charAt(0).toUpperCase() + option.slice(1)
}

function toggle(list: string[], option: string): void {
  const at = list.indexOf(option)
  if (at === -1) {
    list.push(option)
  }
  else {
    list.splice(at, 1)
  }
}

/** A date field back into what the API stores, or `null` to clear it. */
function asTimestamp(value: string): string | null {
  return value ? `${value}T00:00:00Z` : null
}

function submit(): void {
  const name = form.name.trim()
  if (!name) {
    error.value = 'A dish needs a name.'
    return
  }
  error.value = ''
  emit('submit', {
    name,
    online_name: form.online_name.trim(),
    description: form.description.trim(),
    category: form.category,
    short_code: form.short_code.trim(),
    short_code_2: form.short_code_2.trim(),
    hsn_code: form.hsn_code.trim(),
    price: Number(form.price) || 0,
    packing_charges: Number(form.packing_charges) || 0,
    profit_margin: Number(form.profit_margin) || 0,
    weight: Number(form.weight) || 0,
    weight_unit: form.weight_unit,
    diet: form.diet,
    // The empty string means "nobody has said", which is a different thing from goods.
    gst_type: form.gst_type || null,
    order_types: [...form.order_types],
    expose_in: [...form.expose_in],
    allow_decimal_quantity: form.allow_decimal_quantity,
    manufactured_on: asTimestamp(form.manufactured_on),
    expires_on: asTimestamp(form.expires_on),
    image_url: imageUrl.value,
    is_available: form.is_available,
  })
}
</script>

<template>
  <form class="grid gap-6" @submit.prevent="submit">
    <Alert v-if="error" variant="destructive">
      <AlertDescription>{{ error }}</AlertDescription>
    </Alert>

    <!-- Identity ------------------------------------------------------------- -->
    <div class="grid gap-4 sm:grid-cols-3">
      <div class="grid gap-1.5">
        <Label for="item-category">Category</Label>
        <Select v-model="form.category">
          <SelectTrigger id="item-category" class="w-full">
            <SelectValue placeholder="Choose a section" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem v-for="name in categories" :key="name" :value="name">
              {{ name }}
            </SelectItem>
          </SelectContent>
        </Select>
      </div>
      <div class="grid gap-1.5">
        <Label for="item-name">Name <span class="text-destructive">*</span></Label>
        <Input id="item-name" v-model="form.name" maxlength="200" required />
      </div>
      <div class="grid gap-1.5">
        <Label for="item-online-name">Online display name</Label>
        <Input id="item-online-name" v-model="form.online_name" maxlength="200" />
      </div>
    </div>

    <div class="grid gap-4 sm:grid-cols-3">
      <div class="grid gap-1.5">
        <Label for="item-short-code">Short code</Label>
        <Input id="item-short-code" v-model="form.short_code" maxlength="40" />
      </div>
      <div class="grid gap-1.5">
        <Label for="item-short-code-2">Short code 2</Label>
        <Input id="item-short-code-2" v-model="form.short_code_2" maxlength="40" />
      </div>
      <div class="grid gap-1.5">
        <Label for="item-price">Item base price</Label>
        <Input id="item-price" v-model.number="form.price" type="number" min="0" step="0.01" />
      </div>
    </div>

    <!-- Money ---------------------------------------------------------------- -->
    <div class="grid gap-4 sm:grid-cols-3">
      <div class="grid gap-1.5">
        <Label for="item-container">Container charges</Label>
        <Input
          id="item-container"
          v-model.number="form.packing_charges"
          type="number"
          min="0"
          step="0.01"
        />
      </div>
      <div class="grid gap-1.5">
        <Label for="item-weight">Weight / portion</Label>
        <div class="flex gap-2">
          <Input
            id="item-weight"
            v-model.number="form.weight"
            type="number"
            min="0"
            step="0.01"
            class="flex-1"
          />
          <Select v-model="form.weight_unit">
            <SelectTrigger class="w-28" aria-label="Unit">
              <SelectValue placeholder="Unit" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem v-for="unit in options.weight_units" :key="unit" :value="unit">
                {{ unit }}
              </SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>
      <div class="grid gap-1.5">
        <Label for="item-margin">Profit margin (%)</Label>
        <Input
          id="item-margin"
          v-model.number="form.profit_margin"
          type="number"
          min="0"
          max="100"
          step="0.1"
        />
      </div>
    </div>

    <!-- How it is sold -------------------------------------------------------- -->
    <div class="grid gap-4 sm:grid-cols-3">
      <div class="grid gap-2">
        <Label>Dietary</Label>
        <div class="flex flex-wrap gap-2">
          <button
            v-for="option in options.diets"
            :key="option"
            type="button"
            :aria-pressed="form.diet === option"
            class="rounded-full border px-3 py-1.5 text-sm transition-colors outline-hidden focus-visible:ring-2 focus-visible:ring-ring"
            :class="form.diet === option
              ? 'border-primary bg-primary text-primary-foreground'
              : 'border-border hover:bg-accent'"
            @click="form.diet = form.diet === option ? '' : option"
          >
            {{ label(option) }}
          </button>
        </div>
      </div>

      <div class="grid gap-2">
        <Label>Order type</Label>
        <div class="flex flex-wrap gap-2">
          <button
            v-for="option in options.order_types"
            :key="option"
            type="button"
            :aria-pressed="form.order_types.includes(option)"
            class="rounded-full border px-3 py-1.5 text-sm transition-colors outline-hidden focus-visible:ring-2 focus-visible:ring-ring"
            :class="form.order_types.includes(option)
              ? 'border-primary bg-primary text-primary-foreground'
              : 'border-border hover:bg-accent'"
            @click="toggle(form.order_types, option)"
          >
            {{ label(option) }}
          </button>
        </div>
        <p class="text-xs text-muted-foreground">None chosen means all of them.</p>
      </div>

      <div class="grid gap-2">
        <Label>GST type</Label>
        <Select v-model="form.gst_type">
          <SelectTrigger class="w-full" aria-label="GST type">
            <SelectValue placeholder="Not stated" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem v-for="option in options.gst_types" :key="option" :value="option">
              {{ label(option) }}
            </SelectItem>
          </SelectContent>
        </Select>
      </div>
    </div>

    <div class="grid gap-4 sm:grid-cols-3">
      <div class="grid gap-2 sm:col-span-2">
        <Label>Expose this item in</Label>
        <div class="flex flex-wrap gap-2">
          <button
            v-for="option in options.exposures"
            :key="option"
            type="button"
            :aria-pressed="form.expose_in.includes(option)"
            class="rounded-full border px-3 py-1.5 text-sm transition-colors outline-hidden focus-visible:ring-2 focus-visible:ring-ring"
            :class="form.expose_in.includes(option)
              ? 'border-primary bg-primary text-primary-foreground'
              : 'border-border hover:bg-accent'"
            @click="toggle(form.expose_in, option)"
          >
            {{ label(option) }}
          </button>
        </div>
      </div>
      <div class="grid gap-3">
        <div class="flex items-center gap-2.5">
          <Checkbox id="item-decimal" v-model="form.allow_decimal_quantity" />
          <Label for="item-decimal" class="font-normal">Allow decimal quantities</Label>
        </div>
        <div class="flex items-center gap-2.5">
          <Checkbox id="item-available" v-model="form.is_available" />
          <Label for="item-available" class="font-normal">On the menu today</Label>
        </div>
      </div>
    </div>

    <!-- Dates and description -------------------------------------------------- -->
    <div class="grid gap-4 sm:grid-cols-3">
      <div class="grid gap-1.5">
        <Label for="item-made">Manufacturing date</Label>
        <Input id="item-made" v-model="form.manufactured_on" type="date" />
      </div>
      <div class="grid gap-1.5">
        <Label for="item-expires">Expiration date</Label>
        <Input id="item-expires" v-model="form.expires_on" type="date" />
      </div>
      <div class="grid gap-1.5">
        <Label for="item-hsn">HSN code</Label>
        <Input id="item-hsn" v-model="form.hsn_code" maxlength="40" />
      </div>
    </div>

    <div class="grid gap-2">
      <Label>Picture</Label>
      <div class="flex flex-wrap items-center gap-3">
        <div
          class="grid size-20 shrink-0 place-items-center overflow-hidden rounded-lg border border-border bg-muted/40"
        >
          <img v-if="imageUrl" :src="imageUrl" alt="" class="size-full object-cover">
          <FontAwesomeIcon
            v-else
            :icon="['fas', 'image']"
            class="text-lg text-muted-foreground/40"
          />
        </div>
        <div class="grid gap-1.5">
          <div class="flex flex-wrap gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              :disabled="uploading"
              @click="imageInput?.click()"
            >
              <FontAwesomeIcon
                v-if="uploading"
                :icon="['fas', 'spinner']"
                class="motion-safe:animate-spin"
              />
              {{ imageUrl ? 'Replace' : 'Upload' }}
            </Button>
            <Button
              v-if="imageUrl"
              type="button"
              variant="ghost"
              size="sm"
              class="text-destructive hover:text-destructive"
              @click="removeImage"
            >
              Remove
            </Button>
          </div>
          <p class="text-xs text-muted-foreground">PNG, JPEG, WEBP or GIF, up to 2 MB.</p>
        </div>
        <!-- Hidden and clicked from the button: a bare file input cannot be styled to match
             anything, and the native "No file chosen" text is not worth the row. -->
        <input
          ref="imageInput"
          type="file"
          accept="image/png,image/jpeg,image/webp,image/gif"
          class="hidden"
          @change="onImage"
        >
      </div>
    </div>

    <div class="grid gap-1.5">
      <Label for="item-description">Description</Label>
      <Textarea id="item-description" v-model="form.description" rows="3" maxlength="2000" />
      <p class="text-xs text-muted-foreground">
        What a diner reads, and what the assistant has to work with.
      </p>
    </div>

    <div class="flex justify-end gap-2 border-t border-border pt-4">
      <Button type="button" variant="ghost" @click="emit('cancel')">Cancel</Button>
      <Button type="submit" :disabled="busy">
        <FontAwesomeIcon
          v-if="busy"
          :icon="['fas', 'spinner']"
          class="motion-safe:animate-spin"
        />
        {{ item ? 'Save changes' : 'Add item' }}
      </Button>
    </div>
  </form>
</template>
