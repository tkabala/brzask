/** Dates and numbers in the reader's language. */

/** A calendar day ("2026-10-21") without shifting it by the reader's time zone;
 * anything that is not a day (e.g. a mistyped URL) comes back as it is. */
export function formatDay(day: string, language: string): string {
  const moment = new Date(`${day}T00:00:00Z`)
  if (Number.isNaN(moment.getTime())) return day
  return new Intl.DateTimeFormat(language, { dateStyle: 'full', timeZone: 'UTC' }).format(moment)
}

/** The local calendar day after `now`, as a date input wants it (YYYY-MM-DD). */
export function nextDay(now: Date = new Date()): string {
  const next = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1)
  const month = String(next.getMonth() + 1).padStart(2, '0')
  const day = String(next.getDate()).padStart(2, '0')
  return `${String(next.getFullYear())}-${month}-${day}`
}

/** A moment, in the reader's time zone. */
export function formatMoment(moment: string, language: string): string {
  return new Intl.DateTimeFormat(language, { dateStyle: 'medium', timeStyle: 'short' }).format(
    new Date(moment),
  )
}

/** A point in a video, as players show it: "1:35", "12:34", "1:02:05". */
export function formatOffset(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds))
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = String(total % 60).padStart(2, '0')
  return h > 0 ? `${String(h)}:${String(m).padStart(2, '0')}:${s}` : `${String(m)}:${s}`
}

/** How long a run took, once it finished. */
export function seconds(start: string, end: string | null): number | null {
  return end === null ? null : Math.round((Date.parse(end) - Date.parse(start)) / 1000)
}

export interface RunBudget {
  over: boolean
  skipped: string[]
  unpriced: number
}

/** The spending limit a run checked, from its stats; null when none was set. */
export function runBudget(stats: Record<string, unknown>): RunBudget | null {
  const budget = stats.budget
  if (typeof budget !== 'object' || budget === null) return null
  const { over, skipped, unpriced_runs } = budget as Record<string, unknown>
  if (!Array.isArray(skipped)) return null
  return {
    over: over === true,
    skipped: skipped.filter((step): step is string => typeof step === 'string'),
    unpriced: typeof unpriced_runs === 'number' ? unpriced_runs : 0,
  }
}

/** The run's LLM cost, when its stats recorded one. */
export function runCost(stats: Record<string, unknown>): number | null {
  const usage = stats.usage
  if (typeof usage !== 'object' || usage === null) return null
  const cost = (usage as Record<string, unknown>).cost_usd
  return typeof cost === 'number' ? cost : null
}
