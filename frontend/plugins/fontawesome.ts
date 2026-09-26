/**
 * Font Awesome, registered globally as `<FontAwesomeIcon>`.
 *
 * Only the icons the app actually uses are added to the library — importing a whole
 * icon pack (`fas`, `fab`) would ship thousands of unused paths to the browser.
 *
 * Google's mark is deliberately NOT here: FA's brand icons are single-colour, and the
 * sign-in button needs the official four-colour G. See `components/GoogleMark.vue`.
 *
 * `config.autoAddCss = false` stops the core from injecting its stylesheet at run time,
 * which under SSR arrives after the first paint and makes every icon flash at the wrong
 * size. `nuxt.config.ts` loads `@fortawesome/fontawesome-svg-core/styles.css` instead, so
 * the CSS is in the server-rendered HTML from the start.
 *
 * One consequence worth knowing: that stylesheet is unlayered, and unlayered declarations
 * beat every cascade layer regardless of specificity. It sets `display` on `.svg-inline--fa`,
 * so Tailwind's display utilities (`hidden`, `block`, `flex`, ...) do nothing when applied to
 * an icon. Put them on a wrapper element instead.
 */
import { config, library } from '@fortawesome/fontawesome-svg-core'
import {
  faAnglesLeft,
  faAnglesRight,
  faArrowRight,
  faBars,
  faBellConcierge,
  faBookOpen,
  faCashRegister,
  faCheck,
  faChevronDown,
  faChevronUp,
  faChevronRight,
  faCircleExclamation,
  faCircleInfo,
  faCopy,
  faDesktop,
  faEllipsis,
  faEye,
  faFont,
  faGauge,
  faGear,
  faImage,
  faLock,
  faMagnifyingGlass,
  faMinus,
  faKitchenSet,
  faMoon,
  faPen,
  faPlus,
  faPrint,
  faReceipt,
  faList,
  faMap,
  faRightFromBracket,
  faRobot,
  faRotate,
  faSliders,
  faSpinner,
  faTrashCan,
  faSun,
  faUtensils,
  faXmark,
} from '@fortawesome/free-solid-svg-icons'
import { FontAwesomeIcon } from '@fortawesome/vue-fontawesome'

config.autoAddCss = false

library.add(
  faAnglesLeft,
  faAnglesRight,
  faArrowRight,
  faBars,
  faBellConcierge,
  faBookOpen,
  faCashRegister,
  faCheck,
  faChevronDown,
  faChevronUp,
  faChevronRight,
  faCircleExclamation,
  faCircleInfo,
  faCopy,
  faDesktop,
  faEllipsis,
  faEye,
  faFont,
  faGauge,
  faGear,
  faImage,
  faLock,
  faMagnifyingGlass,
  faMinus,
  faKitchenSet,
  faMoon,
  faPen,
  faPlus,
  faPrint,
  faReceipt,
  faList,
  faMap,
  faRightFromBracket,
  faRobot,
  faRotate,
  faSliders,
  faSpinner,
  faTrashCan,
  faSun,
  faUtensils,
  faXmark,
)

export default defineNuxtPlugin((nuxtApp) => {
  nuxtApp.vueApp.component('FontAwesomeIcon', FontAwesomeIcon)
})
