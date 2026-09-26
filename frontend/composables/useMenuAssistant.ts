/**
 * The stand-in for the ordering agent: a search over the loaded menu that talks.
 *
 * Until the real agent (HLD 3.6) is wired to this page, "chat" is this: read the diet and
 * the price out of the question, match the rest against names, descriptions and sections,
 * and answer with dishes. It runs on the phone, over the menu already loaded, so it costs
 * nothing and never waits. The shape - a question in, a sentence and some dishes out - is
 * the same shape the agent will have, so the chat UI does not change when it arrives.
 */
import type { PublicItem, PublicSection } from '~/types/api'

export interface AssistantAnswer {
  text: string
  items: PublicItem[]
}

const STOP_WORDS = new Set([
  'a', 'an', 'the', 'i', 'me', 'my', 'want', 'wants', 'need', 'some', 'something', 'anything',
  'show', 'give', 'get', 'find', 'have', 'do', 'you', 'is', 'are', 'there', 'any', 'please',
  'for', 'with', 'and', 'or', 'of', 'to', 'in', 'on', 'what', 'whats', "what's", 'can',
  'good', 'nice', 'best', 'like', 'menu', 'dish', 'dishes', 'food', 'item', 'items', 'order',
  'suggest', 'recommend', 'option', 'options', 'under', 'below', 'less', 'than', 'upto', 'up',
  'rs', 'rupees', 'price', 'cheap', 'cheaper', 'budget',
])

const MAX_RESULTS = 6

/** `under 200`, `below ₹150`, `less than 300`, `upto 250`. */
function priceCap(query: string): number | null {
  const match = query.match(/(?:under|below|less than|upto|up to|within|max)\s*₹?\s*(\d{2,5})/i)
  return match ? Number(match[1]) : null
}

/** What the question says about diet, if anything. */
function diet(query: string): string | null {
  if (/\bnon[\s-]?veg/i.test(query)) {
    return 'non-veg'
  }
  if (/\begg/i.test(query)) {
    return 'egg'
  }
  if (/\bveg(etarian|etable)?\b/i.test(query)) {
    return 'veg'
  }
  return null
}

function tokens(query: string): string[] {
  return query
    .toLowerCase()
    .replace(/₹|\d+/g, ' ')
    .split(/[^a-z]+/)
    .filter(word => word.length > 2 && !STOP_WORDS.has(word) && !/^(non|veg|egg)$/.test(word))
}

export function answer(query: string, sections: PublicSection[]): AssistantAnswer {
  const cap = priceCap(query)
  const wanted = diet(query)
  const words = tokens(query)

  const scored = sections.flatMap(section =>
    section.items.map((item) => {
      const name = item.name.toLowerCase()
      const description = item.description.toLowerCase()
      const category = section.name.toLowerCase()
      let score = 0
      for (const word of words) {
        if (name.includes(word)) {
          score += 3
        }
        else if (category.includes(word)) {
          score += 2
        }
        else if (description.includes(word)) {
          score += 1
        }
      }
      return { item, score }
    }),
  )
    .filter(({ item, score }) =>
      (words.length === 0 || score > 0)
      && (wanted === null || item.diet === wanted)
      && (cap === null || item.price_from <= cap),
    )
    .sort((a, b) => b.score - a.score || a.item.price_from - b.item.price_from)
    .slice(0, MAX_RESULTS)

  const items = scored.map(({ item }) => item)
  const asked = [
    words.length ? `“${words.join(' ')}”` : '',
    wanted ? { 'veg': 'veg', 'non-veg': 'non-veg', 'egg': 'egg' }[wanted] : '',
    cap !== null ? `under ₹${cap}` : '',
  ].filter(Boolean).join(', ')

  if (!items.length) {
    return {
      text: asked
        ? `Nothing on the menu quite matches ${asked}. Try a dish name, a section, or something like “veg under 150”.`
        : 'Tell me what you feel like — a dish, a section, veg or non-veg, or a budget.',
      items: [],
    }
  }
  const lead = items.length === 1 ? 'One thing fits' : `Here ${items.length === MAX_RESULTS ? 'are the best' : `are ${items.length}`}`
  return {
    text: asked ? `${lead} for ${asked}. Tap Add to put one on your order.` : `${lead} to start with. Tap Add to put one on your order.`,
    items,
  }
}

/** Openers, so the first question is a tap, not a blank field. */
export const SUGGESTIONS = [
  'Something veg under ₹150',
  'Chicken combos',
  'Egg dishes',
  'Non-veg under ₹250',
]
