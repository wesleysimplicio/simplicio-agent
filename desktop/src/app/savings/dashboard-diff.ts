// Pure diff/highlight logic for Live Activity: given the previously-rendered
// parsed summary (or `null` on first load) and a freshly-parsed one, decide
// (a) whether this poll actually carries a new generation of data — drives
// the header's stronger pulse ring — and (b) which `recent` feed entries are
// new since last time — drives the feed's slide-in + glow highlight. No
// React/DOM here so this unit-tests with plain summary objects.

import type { DashboardRecentEvent, DashboardTotals, ParsedDashboardSummary } from './dashboard-parse'

export interface DashboardDiff {
  /** True when this summary is a genuinely new generation of data (not just
   * a re-fetch that resolved to the same content). False on the very first
   * load — there is nothing to have "arrived" relative to. */
  isNewGeneration: boolean
  /** Which `totals` fields actually changed value since the previous
   * summary — drives the hero counters' flash highlight. Empty on first
   * load (nothing to flash against). */
  changedTotals: ReadonlySet<keyof DashboardTotals>
  /** `recentEventKey`s present in `next.recent` but not in `prev.recent` —
   * drives the feed's slide-in + glow. Empty on first load. */
  newRecentKeys: ReadonlySet<string>
}

/** A best-effort freshness fingerprint for a summary: prefers the server's
 * own `generatedAt` marker; falls back to the newest recent-feed entry's
 * content key, then to the raw event count — so "did new data arrive" is
 * still detectable when the backend omits `generated_at` outright. */
function generationFingerprint(summary: ParsedDashboardSummary): null | string {
  if (summary.generatedAt !== null) {
    return `gen:${summary.generatedAt}`
  }

  if (summary.recent.length > 0) {
    return `recent:${summary.recent[0].key}`
  }

  if (summary.totals.events !== null) {
    return `events:${summary.totals.events}`
  }

  return null
}

const TOTALS_KEYS: readonly (keyof DashboardTotals)[] = [
  'events',
  'spent',
  'baseline',
  'saved',
  'savedPct',
  'costSavedUsd'
]

function diffTotals(prev: DashboardTotals, next: DashboardTotals): ReadonlySet<keyof DashboardTotals> {
  const changed = new Set<keyof DashboardTotals>()

  for (const key of TOTALS_KEYS) {
    if (prev[key] !== next[key]) {
      changed.add(key)
    }
  }

  return changed
}

function diffRecent(prev: readonly DashboardRecentEvent[], next: readonly DashboardRecentEvent[]): ReadonlySet<string> {
  const prevKeys = new Set(prev.map(event => event.key))
  const newKeys = new Set<string>()

  for (const event of next) {
    if (!prevKeys.has(event.key)) {
      newKeys.add(event.key)
    }
  }

  return newKeys
}

export function diffDashboardSummary(prev: null | ParsedDashboardSummary, next: ParsedDashboardSummary): DashboardDiff {
  if (prev === null) {
    return { changedTotals: new Set(), isNewGeneration: false, newRecentKeys: new Set() }
  }

  const prevFingerprint = generationFingerprint(prev)
  const nextFingerprint = generationFingerprint(next)
  // Two summaries with no fingerprint at all (no generatedAt, no recent
  // events, no events total) count as unchanged — there's genuinely nothing
  // to compare, so claiming "new" would be a fabricated pulse.
  const isNewGeneration =
    prevFingerprint !== null || nextFingerprint !== null ? prevFingerprint !== nextFingerprint : false

  return {
    changedTotals: diffTotals(prev.totals, next.totals),
    isNewGeneration,
    newRecentKeys: diffRecent(prev.recent, next.recent)
  }
}
