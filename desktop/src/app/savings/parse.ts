// Defensive, pure parsing of `simplicio savings report --json` output.
//
// The report shape is not contractually fixed here — it comes from a Rust
// CLI whose aggregate JSON may or may not carry every field depending on
// runtime version. Every extractor below tolerates a missing/malformed field
// by returning `null` rather than guessing a number. Callers render `null`
// as "—" (unknown). This file must never synthesize a plausible-looking
// figure — that would defeat the entire point of the measured/estimated
// distinction this panel exists to show honestly.

import { isProofKind, type ProofKind, proofKindRank, type SavingsRawReport } from './types'

export interface SavingsTotals {
  spent: null | number
  baseline: null | number
  saved: null | number
  pct: null | number
}

export interface SavingsEvent {
  /** Synthesized when the report doesn't carry a stable id. */
  id: string
  timestamp: null | string
  /** Epoch ms, when `timestamp` parses as a real date; used for sorting/chart. */
  timestampMs: null | number
  spent: null | number
  baseline: null | number
  saved: null | number
  pct: null | number
  proofKind: null | ProofKind
  session: null | string
  repo: null | string
  model: null | string
}

export interface TimeSeriesPoint {
  day: string
  savedTotal: null | number
  baselineTotal: null | number
  actualTotal: null | number
  savedPercent: null | number
}

export interface DimensionSlice {
  key: string
  savedTotal: null | number
  savedPercent: null | number
}

export interface SavingsDimensions {
  timeSeries: TimeSeriesPoint[]
  byModel: DimensionSlice[]
  byProof: DimensionSlice[]
}

export interface ParsedSavingsReport {
  totals: SavingsTotals
  events: SavingsEvent[]
  /** True when at least one event carries a session/repo/model tag. */
  hasSessionGranularity: boolean
  dimensions: SavingsDimensions
  /**
   * The strongest proof kind present (measured > replayed > benchmark >
   * estimated), so the headline can show ONE honest label instead of
   * blending evidence tiers. `null` when no event carries a recognizable
   * proof kind at all.
   */
  dominantProofKind: null | ProofKind
  /** True when events carry more than one distinct proof kind — the caller
   * uses this to add a "mixed evidence" disclosure next to the headline
   * rather than silently presenting the dominant kind as if it were the
   * whole story. */
  mixedProofKinds: boolean
}

const EMPTY_TOTALS: SavingsTotals = { spent: null, baseline: null, saved: null, pct: null }

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

function proofKindOrNull(value: unknown): null | ProofKind {
  return isProofKind(value) ? value : null
}

function timestampMsOrNull(value: null | string): null | number {
  if (!value) {
    return null
  }

  // Bare epoch seconds/millis (common in ledger dumps) as well as ISO strings.
  const asNumber = Number(value)

  if (Number.isFinite(asNumber) && /^\d+$/.test(value.trim())) {
    return asNumber > 1e12 ? asNumber : asNumber * 1000
  }

  const parsed = Date.parse(value)

  return Number.isFinite(parsed) ? parsed : null
}

/** First truthy value found by trying each key on the record, else undefined. */
function pick(record: Record<string, unknown>, keys: readonly string[]): unknown {
  for (const key of keys) {
    if (record[key] !== undefined && record[key] !== null) {
      return record[key]
    }
  }

  return undefined
}

const SPENT_KEYS = ['spent', 'spent_tokens', 'tokens_spent', 'actual', 'used'] as const
const BASELINE_KEYS = ['baseline', 'baseline_tokens', 'tokens_baseline', 'without_simplicio'] as const
// `saved_total` is the real key on `simplicio savings report --json`'s
// per-record entries (they carry no spent/baseline, only the saved total).
const SAVED_KEYS = ['saved', 'saved_total', 'saved_tokens', 'tokens_saved', 'delta'] as const
const PCT_KEYS = ['pct', 'percent', 'percentage', 'saved_percent', 'saved_pct', 'pct_saved'] as const
const PROOF_KEYS = ['proof_kind', 'proofKind', 'kind'] as const
const TIMESTAMP_KEYS = ['timestamp', 'ts', 'recorded_at', 'created_at', 'time'] as const
const SESSION_KEYS = ['session', 'session_id', 'sessionId'] as const
const REPO_KEYS = ['repo', 'repository', 'project'] as const
const MODEL_KEYS = ['model', 'model_id', 'modelId'] as const
const ID_KEYS = ['id', 'event_id', 'eventId', 'uuid'] as const

function extractTotals(record: Record<string, unknown>): SavingsTotals {
  const spent = numOrNull(pick(record, SPENT_KEYS))
  const baseline = numOrNull(pick(record, BASELINE_KEYS))
  let saved = numOrNull(pick(record, SAVED_KEYS))
  let pct = numOrNull(pick(record, PCT_KEYS))

  // Derive saved/pct from spent+baseline when the report omits them outright
  // (still real arithmetic on real reported numbers, not a fabricated figure).
  if (saved === null && spent !== null && baseline !== null) {
    saved = baseline - spent
  }

  if (pct === null && saved !== null && baseline !== null && baseline > 0) {
    pct = Math.round((saved / baseline) * 100)
  }

  return { spent, baseline, saved, pct }
}

function totalsSource(report: Record<string, unknown>): Record<string, unknown> {
  const nested = pick(report, ['totals', 'aggregate', 'aggregates', 'summary'])

  return isRecord(nested) ? nested : report
}

function eventsSource(report: Record<string, unknown>): unknown[] {
  // `events` in the runtime's `simplicio.savings-event/v1` report is a COUNT
  // (integer), not the list -- the actual per-event array lives under
  // `records` (or `sessions`/`entries`/`items` in other report shapes). Scan
  // every candidate key and take the first one that is actually an array,
  // instead of trusting the first key that merely exists.
  for (const key of ['records', 'sessions', 'entries', 'items', 'events']) {
    const value = report[key]
    if (Array.isArray(value)) {
      return value
    }
  }

  return []
}

function parseEvent(raw: unknown, index: number): null | SavingsEvent {
  if (!isRecord(raw)) {
    return null
  }

  const timestamp = strOrNull(pick(raw, TIMESTAMP_KEYS))
  const { baseline, pct, saved, spent } = extractTotals(raw)

  return {
    baseline,
    id: strOrNull(pick(raw, ID_KEYS)) ?? `event-${index}`,
    model: strOrNull(pick(raw, MODEL_KEYS)),
    pct,
    proofKind: proofKindOrNull(pick(raw, PROOF_KEYS)),
    repo: strOrNull(pick(raw, REPO_KEYS)),
    saved,
    session: strOrNull(pick(raw, SESSION_KEYS)),
    spent,
    timestamp,
    timestampMs: timestampMsOrNull(timestamp)
  }
}

const EMPTY_DIMENSIONS: SavingsDimensions = { byModel: [], byProof: [], timeSeries: [] }

/**
 * `report.dimensions` — daily time series plus per-model / per-proof-kind
 * slices. Slices tolerate both shapes the CLI could emit: an array of
 * `{key, saved_total, saved_percent}` entries or an object map
 * `key -> {saved_total, saved_percent}`. Absent dimension = empty list
 * (the UI skips the section; no placeholder is invented).
 */
function parseDimensionSlices(raw: unknown): DimensionSlice[] {
  const entries: DimensionSlice[] = []

  if (Array.isArray(raw)) {
    for (const entry of raw) {
      if (!isRecord(entry)) {
        continue
      }

      const key = strOrNull(entry.key) ?? strOrNull(entry.name)

      if (!key) {
        continue
      }

      entries.push({
        key,
        savedPercent: numOrNull(pick(entry, ['saved_percent', 'savedPercent', 'pct'])),
        savedTotal: numOrNull(pick(entry, ['saved_total', 'savedTotal', 'saved']))
      })
    }

    return entries
  }

  if (isRecord(raw)) {
    for (const [key, value] of Object.entries(raw)) {
      if (isRecord(value)) {
        entries.push({
          key,
          savedPercent: numOrNull(pick(value, ['saved_percent', 'savedPercent', 'pct'])),
          savedTotal: numOrNull(pick(value, ['saved_total', 'savedTotal', 'saved']))
        })
      } else if (numOrNull(value) !== null) {
        entries.push({ key, savedPercent: null, savedTotal: numOrNull(value) })
      }
    }
  }

  return entries
}

function parseDimensions(report: Record<string, unknown>): SavingsDimensions {
  const dimensions = report.dimensions

  if (!isRecord(dimensions)) {
    return EMPTY_DIMENSIONS
  }

  const rawSeries = pick(dimensions, ['time_series', 'timeSeries'])
  const timeSeries: TimeSeriesPoint[] = []

  if (Array.isArray(rawSeries)) {
    for (const entry of rawSeries) {
      if (!isRecord(entry)) {
        continue
      }

      const day = strOrNull(pick(entry, ['day', 'date']))

      if (!day) {
        continue
      }

      timeSeries.push({
        actualTotal: numOrNull(pick(entry, ['actual_total', 'actualTotal', 'spent'])),
        baselineTotal: numOrNull(pick(entry, ['baseline_total', 'baselineTotal', 'baseline'])),
        day,
        savedPercent: numOrNull(pick(entry, ['saved_percent', 'savedPercent', 'pct'])),
        savedTotal: numOrNull(pick(entry, ['saved_total', 'savedTotal', 'saved']))
      })
    }
  }

  return {
    byModel: parseDimensionSlices(pick(dimensions, ['by_model', 'byModel'])),
    byProof: parseDimensionSlices(pick(dimensions, ['by_proof', 'byProof', 'by_proof_kind'])),
    timeSeries
  }
}

/**
 * The single strongest proof kind across events, plus whether more than one
 * distinct kind is present. `measured` always wins when present (real
 * receipts outrank every heuristic), otherwise the strongest of whatever
 * remains — never an average or a majority vote, which would blur exactly
 * the distinction this exists to preserve.
 */
function dominantProof(events: readonly SavingsEvent[]): { dominant: null | ProofKind; mixed: boolean } {
  const kinds = new Set<ProofKind>()

  for (const event of events) {
    if (event.proofKind) {
      kinds.add(event.proofKind)
    }
  }

  if (kinds.size === 0) {
    return { dominant: null, mixed: false }
  }

  let dominant: ProofKind | null = null

  for (const kind of kinds) {
    if (dominant === null || proofKindRank(kind) < proofKindRank(dominant)) {
      dominant = kind
    }
  }

  return { dominant, mixed: kinds.size > 1 }
}

export function parseSavingsReport(report: SavingsRawReport): ParsedSavingsReport {
  if (!isRecord(report)) {
    return {
      dimensions: EMPTY_DIMENSIONS,
      dominantProofKind: null,
      events: [],
      hasSessionGranularity: false,
      mixedProofKinds: false,
      totals: EMPTY_TOTALS
    }
  }

  const totals = extractTotals(totalsSource(report))
  const events = eventsSource(report)
    .map((raw, index) => parseEvent(raw, index))
    .filter((event): event is SavingsEvent => event !== null)
  const dimensions = parseDimensions(report)

  // No explicit totals block? Fall back to summing whatever events carry
  // real numbers, so the hero cards aren't blank when only a flat event list
  // is present.
  const totalsAreEmpty = totals.spent === null && totals.baseline === null && totals.saved === null
  let derivedTotals = totalsAreEmpty && events.length > 0 ? sumEventTotals(events) : totals

  // Still missing baseline (real per-event records carry only `saved_total`,
  // no spent/baseline)? The runtime always reports a daily `time_series`
  // dimension with real baseline_total/saved_total/saved_percent per day --
  // sum that as a further honest fallback instead of leaving the hero blank.
  if (derivedTotals.baseline === null && dimensions.timeSeries.length > 0) {
    derivedTotals = sumTimeSeriesTotals(dimensions.timeSeries, derivedTotals)
  }

  const { dominant, mixed } = dominantProof(events)

  return {
    dimensions,
    dominantProofKind: dominant,
    events: [...events].sort((a, b) => (b.timestampMs ?? 0) - (a.timestampMs ?? 0)),
    hasSessionGranularity: events.some(event => event.session !== null || event.repo !== null),
    mixedProofKinds: mixed,
    totals: derivedTotals
  }
}

function sumTimeSeriesTotals(timeSeries: readonly TimeSeriesPoint[], fallback: SavingsTotals): SavingsTotals {
  let spent: null | number = null
  let baseline: null | number = null
  let saved: null | number = null

  for (const point of timeSeries) {
    if (point.actualTotal !== null) spent = (spent ?? 0) + point.actualTotal
    if (point.baselineTotal !== null) baseline = (baseline ?? 0) + point.baselineTotal
    if (point.savedTotal !== null) saved = (saved ?? 0) + point.savedTotal
  }

  if (saved === null && spent !== null && baseline !== null) {
    saved = baseline - spent
  }

  const pct = saved !== null && baseline !== null && baseline > 0 ? Math.round((saved / baseline) * 100) : null

  return {
    baseline: baseline ?? fallback.baseline,
    pct: pct ?? fallback.pct,
    saved: saved ?? fallback.saved,
    spent: spent ?? fallback.spent
  }
}

function sumEventTotals(events: readonly SavingsEvent[]): SavingsTotals {
  let spent: null | number = null
  let baseline: null | number = null
  let saved: null | number = null
  let sawSaved = false

  for (const event of events) {
    if (event.spent !== null) {
      spent = (spent ?? 0) + event.spent
    }

    if (event.baseline !== null) {
      baseline = (baseline ?? 0) + event.baseline
    }

    // Sum `saved` directly when the record reports it -- real runtime
    // records (e.g. `records[]` in `savings report`) carry only
    // `saved_total`, no per-event spent/baseline breakdown to derive from.
    if (event.saved !== null) {
      saved = (saved ?? 0) + event.saved
      sawSaved = true
    }
  }

  if (!sawSaved && spent !== null && baseline !== null) {
    saved = baseline - spent
  }

  const pct = saved !== null && baseline !== null && baseline > 0 ? Math.round((saved / baseline) * 100) : null

  return { baseline, pct, saved, spent }
}

export interface CumulativePoint {
  timestampMs: number
  cumulativeSaved: number
}

/** Ascending-time cumulative-saved series for the trend chart. Events with no
 * usable saved figure or timestamp are skipped rather than plotted at zero. */
export function cumulativeSavedSeries(events: readonly SavingsEvent[]): CumulativePoint[] {
  const usable = events
    .filter((event): event is SavingsEvent & { saved: number; timestampMs: number } => {
      return event.saved !== null && event.timestampMs !== null
    })
    .sort((a, b) => a.timestampMs - b.timestampMs)

  let running = 0

  return usable.map(event => {
    running += event.saved

    return { cumulativeSaved: running, timestampMs: event.timestampMs }
  })
}

/** Cumulative-saved series from the report's daily time_series dimension.
 * Days with no real saved figure or unparseable date are skipped. */
export function cumulativeFromTimeSeries(series: readonly TimeSeriesPoint[]): CumulativePoint[] {
  const usable = series
    .map(point => ({ saved: point.savedTotal, timestampMs: Date.parse(point.day) }))
    .filter((point): point is { saved: number; timestampMs: number } => {
      return point.saved !== null && Number.isFinite(point.timestampMs)
    })
    .sort((a, b) => a.timestampMs - b.timestampMs)

  let running = 0

  return usable.map(point => {
    running += point.saved

    return { cumulativeSaved: running, timestampMs: point.timestampMs }
  })
}
