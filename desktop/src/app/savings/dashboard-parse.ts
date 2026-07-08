// Defensive, pure parsing of `simplicio dashboard`'s summary payload (the
// richer aggregation behind Live Activity: totals, by_provider, by_repo,
// timeseries buckets, and a `recent` per-event feed). Same honesty contract
// as `parse.ts` for the savings report — every extractor tolerates a
// missing/malformed field by returning `null` rather than guessing, and
// every dimension tolerates both an array-of-entries or an object-map shape
// since the exact wire format isn't pinned here. No React/DOM: everything
// unit-tests with plain objects.

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function numOrNull(value: unknown): null | number {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value
  }

  if (typeof value === 'string' && value.trim() !== '') {
    const parsed = Number(value)

    return Number.isFinite(parsed) ? parsed : null
  }

  return null
}

function strOrNull(value: unknown): null | string {
  return typeof value === 'string' && value.trim() !== '' ? value : null
}

function pick(record: Record<string, unknown>, keys: readonly string[]): unknown {
  for (const key of keys) {
    if (record[key] !== undefined && record[key] !== null) {
      return record[key]
    }
  }

  return undefined
}

function timestampMsOrNull(value: null | string): null | number {
  if (!value) {
    return null
  }

  const trimmed = value.trim()

  if (/^\d+$/.test(trimmed)) {
    const asNumber = Number(trimmed)

    return asNumber > 1e12 ? asNumber : asNumber * 1000
  }

  const parsed = Date.parse(value)

  return Number.isFinite(parsed) ? parsed : null
}

// ---------------------------------------------------------------------------
// Totals
// ---------------------------------------------------------------------------

export interface DashboardTotals {
  events: null | number
  spent: null | number
  baseline: null | number
  saved: null | number
  savedPct: null | number
  costSavedUsd: null | number
}

const EMPTY_TOTALS: DashboardTotals = {
  baseline: null,
  costSavedUsd: null,
  events: null,
  saved: null,
  savedPct: null,
  spent: null
}

function parseTotals(raw: unknown): DashboardTotals {
  if (!isRecord(raw)) {
    return EMPTY_TOTALS
  }

  const events = numOrNull(pick(raw, ['events', 'event_count', 'total_events']))
  const spent = numOrNull(pick(raw, ['spent', 'spent_tokens']))
  const baseline = numOrNull(pick(raw, ['baseline', 'baseline_tokens']))
  let saved = numOrNull(pick(raw, ['saved', 'saved_tokens', 'saved_total']))
  let savedPct = numOrNull(pick(raw, ['saved_pct', 'savedPct', 'saved_percent']))
  const costSavedUsd = numOrNull(pick(raw, ['cost_saved_usd', 'costSavedUsd', 'cost_saved']))

  // Derive saved/pct from spent+baseline only when the report omits them
  // outright — real arithmetic on real reported numbers, never a guess.
  if (saved === null && spent !== null && baseline !== null) {
    saved = baseline - spent
  }

  if (savedPct === null && saved !== null && baseline !== null && baseline > 0) {
    savedPct = Math.round((saved / baseline) * 100)
  }

  return { baseline, costSavedUsd, events, saved, savedPct, spent }
}

// ---------------------------------------------------------------------------
// Dimension slices (by_provider / by_repo) — array-of-entries or object-map
// ---------------------------------------------------------------------------

export interface DashboardDimensionSlice {
  key: string
  spent: null | number
  saved: null | number
  events: null | number
}

function parseSliceFields(entry: Record<string, unknown>): Omit<DashboardDimensionSlice, 'key'> {
  return {
    events: numOrNull(pick(entry, ['events', 'event_count', 'count'])),
    saved: numOrNull(pick(entry, ['saved', 'saved_total', 'saved_tokens'])),
    spent: numOrNull(pick(entry, ['spent', 'spent_tokens']))
  }
}

function parseDimensionSlices(raw: unknown): DashboardDimensionSlice[] {
  const entries: DashboardDimensionSlice[] = []

  if (Array.isArray(raw)) {
    for (const entry of raw) {
      if (!isRecord(entry)) {
        continue
      }

      const key = strOrNull(entry.key) ?? strOrNull(entry.name)

      if (!key) {
        continue
      }

      entries.push({ key, ...parseSliceFields(entry) })
    }

    return entries
  }

  if (isRecord(raw)) {
    for (const [key, value] of Object.entries(raw)) {
      if (isRecord(value)) {
        entries.push({ key, ...parseSliceFields(value) })
      } else {
        const saved = numOrNull(value)

        if (saved !== null) {
          entries.push({ events: null, key, saved, spent: null })
        }
      }
    }
  }

  return entries
}

// ---------------------------------------------------------------------------
// Timeseries buckets
// ---------------------------------------------------------------------------

export interface DashboardTimeseriesPoint {
  bucket: string
  timestampMs: null | number
  spent: null | number
  saved: null | number
  events: null | number
}

function parseTimeseries(raw: unknown): DashboardTimeseriesPoint[] {
  if (!Array.isArray(raw)) {
    return []
  }

  const points: DashboardTimeseriesPoint[] = []

  for (const entry of raw) {
    if (!isRecord(entry)) {
      continue
    }

    const bucket = strOrNull(pick(entry, ['bucket', 'hour', 'day', 'ts', 'time', 'period']))

    if (!bucket) {
      continue
    }

    points.push({
      bucket,
      events: numOrNull(pick(entry, ['events', 'event_count', 'count'])),
      saved: numOrNull(pick(entry, ['saved', 'saved_total', 'saved_tokens'])),
      spent: numOrNull(pick(entry, ['spent', 'spent_tokens'])),
      timestampMs: timestampMsOrNull(bucket)
    })
  }

  // Ascending by time when parseable, else keep report order (stable sort).
  return points
    .map((point, index) => ({ index, point }))
    .sort((a, b) => {
      if (a.point.timestampMs !== null && b.point.timestampMs !== null) {
        return a.point.timestampMs - b.point.timestampMs
      }

      return a.index - b.index
    })
    .map(({ point }) => point)
}

// ---------------------------------------------------------------------------
// Recent event feed
// ---------------------------------------------------------------------------

export interface DashboardRecentEvent {
  /** Deterministic content key (no stable backend id in the wire format) —
   * identical fields across two polls produce the same key, so it also
   * doubles as the React list key and the "is this a new item" identity. */
  key: string
  ts: null | string
  timestampMs: null | number
  task: null | string
  provider: null | string
  model: null | string
  repo: null | string
  surface: null | string
  spent: null | number
  saved: null | number
}

/** Deterministic identity for a recent-feed event from its content fields —
 * shared between the parser (assigns `key`) and the diff module (detects
 * which keys are new since the previous poll). */
export function recentEventKey(fields: {
  model: null | string
  provider: null | string
  repo: null | string
  saved: null | number
  spent: null | number
  task: null | string
  ts: null | string
}): string {
  return [fields.ts, fields.task, fields.provider, fields.model, fields.repo, fields.spent, fields.saved]
    .map(v => (v === null || v === undefined ? '' : String(v)))
    .join('|')
}

function surfaceOrNull(raw: Record<string, unknown>): null | string {
  const single = strOrNull(raw.surface)

  if (single) {
    return single
  }

  if (Array.isArray(raw.surfaces)) {
    const names = raw.surfaces.filter((v): v is string => typeof v === 'string')

    return names.length > 0 ? names.join(' · ') : null
  }

  return null
}

function parseRecentEvent(raw: unknown): null | DashboardRecentEvent {
  if (!isRecord(raw)) {
    return null
  }

  const ts = strOrNull(pick(raw, ['ts', 'timestamp', 'time']))
  const task = strOrNull(pick(raw, ['task', 'task_title', 'taskTitle', 'title']))
  const provider = strOrNull(raw.provider)
  const model = strOrNull(raw.model)
  const repo = strOrNull(pick(raw, ['repo', 'repository']))
  const spent = numOrNull(pick(raw, ['spent', 'spent_tokens']))
  const saved = numOrNull(pick(raw, ['saved', 'saved_total', 'saved_tokens']))

  return {
    key: recentEventKey({ model, provider, repo, saved, spent, task, ts }),
    model,
    provider,
    repo,
    saved,
    spent,
    surface: surfaceOrNull(raw),
    task,
    timestampMs: timestampMsOrNull(ts),
    ts
  }
}

function parseRecent(raw: unknown): DashboardRecentEvent[] {
  if (!Array.isArray(raw)) {
    return []
  }

  return raw.map(entry => parseRecentEvent(entry)).filter((event): event is DashboardRecentEvent => event !== null)
}

// ---------------------------------------------------------------------------
// Top-level summary
// ---------------------------------------------------------------------------

export interface ParsedDashboardSummary {
  /** Freshness marker the report may carry (`generated_at`/`as_of`); used to
   * detect a genuinely new poll result vs. an unchanged re-fetch. `null`
   * when the backend doesn't report one — the diff module falls back to
   * content-based freshness detection in that case. */
  generatedAt: null | string
  totals: DashboardTotals
  byProvider: DashboardDimensionSlice[]
  byRepo: DashboardDimensionSlice[]
  timeseries: DashboardTimeseriesPoint[]
  recent: DashboardRecentEvent[]
}

const EMPTY_SUMMARY: ParsedDashboardSummary = {
  byProvider: [],
  byRepo: [],
  generatedAt: null,
  recent: [],
  timeseries: [],
  totals: EMPTY_TOTALS
}

export function parseDashboardSummary(raw: unknown): ParsedDashboardSummary {
  if (!isRecord(raw)) {
    return EMPTY_SUMMARY
  }

  return {
    byProvider: parseDimensionSlices(pick(raw, ['by_provider', 'byProvider'])),
    byRepo: parseDimensionSlices(pick(raw, ['by_repo', 'byRepo'])),
    generatedAt: strOrNull(pick(raw, ['generated_at', 'generatedAt', 'as_of'])),
    recent: parseRecent(pick(raw, ['recent', 'recent_events', 'recentEvents'])),
    timeseries: parseTimeseries(pick(raw, ['timeseries', 'time_series', 'timeSeries'])),
    totals: parseTotals(pick(raw, ['totals', 'aggregate', 'summary']) ?? raw)
  }
}
