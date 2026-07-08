import { describe, expect, it } from 'vitest'

import { cumulativeFromTimeSeries, cumulativeSavedSeries, parseSavingsReport } from './parse'

describe('parseSavingsReport', () => {
  it('returns empty, honest defaults for a non-object report', () => {
    expect(parseSavingsReport(null)).toEqual({
      dimensions: { byModel: [], byProof: [], timeSeries: [] },
      events: [],
      hasSessionGranularity: false,
      totals: { baseline: null, pct: null, saved: null, spent: null }
    })
  })
})

describe('parseSavingsReport totals', () => {
  it('reads a totals block using the documented field names', () => {
    const parsed = parseSavingsReport({
      totals: { baseline: 1000, saved: 800, spent: 200 }
    })

    expect(parsed.totals).toEqual({ baseline: 1000, pct: 80, saved: 800, spent: 200 })
  })

  it('derives saved and pct when the report only reports spent/baseline', () => {
    const parsed = parseSavingsReport({ aggregate: { baseline: 500, spent: 100 } })

    expect(parsed.totals).toEqual({ baseline: 500, pct: 80, saved: 400, spent: 100 })
  })

  it('never invents a number for a field that is genuinely absent', () => {
    const parsed = parseSavingsReport({ totals: { spent: 100 } })

    expect(parsed.totals).toEqual({ baseline: null, pct: null, saved: null, spent: 100 })
  })

  it('falls back to summing events when there is no totals/aggregate block', () => {
    const parsed = parseSavingsReport({
      events: [
        { baseline: 100, spent: 20 },
        { baseline: 200, spent: 40 }
      ]
    })

    expect(parsed.totals).toEqual({ baseline: 300, pct: 80, saved: 240, spent: 60 })
  })
})

describe('parseSavingsReport events', () => {
  it('tolerates missing fields per-event instead of throwing', () => {
    const parsed = parseSavingsReport({
      events: [{ note: 'no recognizable fields at all' }]
    })

    expect(parsed.events).toHaveLength(1)
    expect(parsed.events[0]).toMatchObject({
      baseline: null,
      model: null,
      proofKind: null,
      repo: null,
      saved: null,
      session: null,
      spent: null,
      timestamp: null
    })
  })

  it('prefers `records` over an integer `events` count (real runtime shape)', () => {
    // `simplicio savings report --json` returns `events` as a COUNT, not a
    // list -- the actual per-event array is `records`. Regression test for
    // a bug where the count silently won and the UI showed "no savings".
    const parsed = parseSavingsReport({
      events: 8,
      // real `records[]` entries carry `saved_total`, not spent/baseline.
      records: [{ saved_total: 2000 }]
    })

    expect(parsed.events).toHaveLength(1)
    expect(parsed.events[0].saved).toBe(2000)
  })

  it('reads proof_kind and only accepts the two known values', () => {
    const parsed = parseSavingsReport({
      events: [
        { proof_kind: 'measured', spent: 1 },
        { proof_kind: 'estimated', spent: 1 },
        { proof_kind: 'guessed', spent: 1 }
      ]
    })

    expect(parsed.events.map(e => e.proofKind)).toEqual(['measured', 'estimated', null])
  })

  it('detects session granularity from session/repo tags', () => {
    const withSession = parseSavingsReport({ events: [{ session: 'abc', spent: 1 }] })
    const withoutSession = parseSavingsReport({ events: [{ spent: 1 }] })

    expect(withSession.hasSessionGranularity).toBe(true)
    expect(withoutSession.hasSessionGranularity).toBe(false)
  })

  it('sorts events newest-first', () => {
    const parsed = parseSavingsReport({
      events: [
        { spent: 1, timestamp: '2026-01-01T00:00:00Z' },
        { spent: 1, timestamp: '2026-06-01T00:00:00Z' }
      ]
    })

    expect(parsed.events[0].timestamp).toBe('2026-06-01T00:00:00Z')
  })

  it('accepts string-typed numeric fields from a loosely-typed CLI dump', () => {
    const parsed = parseSavingsReport({ events: [{ baseline: '100', spent: '20' }] })

    expect(parsed.events[0]).toMatchObject({ baseline: 100, saved: 80, spent: 20 })
  })
})

describe('cumulativeSavedSeries', () => {
  it('produces a running total ordered by ascending time', () => {
    const parsed = parseSavingsReport({
      events: [
        { saved: 100, spent: 1, timestamp: '2026-01-02T00:00:00Z' },
        { saved: 50, spent: 1, timestamp: '2026-01-01T00:00:00Z' }
      ]
    })

    const series = cumulativeSavedSeries(parsed.events)

    expect(series.map(p => p.cumulativeSaved)).toEqual([50, 150])
  })

  it('skips events with no usable saved figure or timestamp', () => {
    const parsed = parseSavingsReport({
      events: [
        { saved: 10, timestamp: '2026-01-01T00:00:00Z' },
        { spent: 1, timestamp: '2026-01-02T00:00:00Z' }, // no `saved`
        { saved: 5 } // no timestamp
      ]
    })

    const series = cumulativeSavedSeries(parsed.events)

    expect(series).toEqual([{ cumulativeSaved: 10, timestampMs: Date.parse('2026-01-01T00:00:00Z') }])
  })
})

describe('parseSavingsReport dimensions', () => {
  it('parses time_series, by_model, and by_proof (array-of-entries shape)', () => {
    const parsed = parseSavingsReport({
      dimensions: {
        by_model: [{ key: 'gemma4', saved_percent: 80, saved_total: 4000 }],
        by_proof: [
          { key: 'measured', saved_total: 3000 },
          { key: 'estimated', saved_total: 1000 }
        ],
        time_series: [{ actual_total: 0, baseline_total: 500, day: '2026-07-07', saved_percent: 100, saved_total: 500 }]
      }
    })

    expect(parsed.dimensions.timeSeries).toEqual([
      { actualTotal: 0, baselineTotal: 500, day: '2026-07-07', savedPercent: 100, savedTotal: 500 }
    ])
    expect(parsed.dimensions.byModel).toEqual([{ key: 'gemma4', savedPercent: 80, savedTotal: 4000 }])
    expect(parsed.dimensions.byProof.map(slice => slice.key)).toEqual(['measured', 'estimated'])
  })

  it('parses the object-map slice shape and skips unusable entries', () => {
    const parsed = parseSavingsReport({
      dimensions: {
        by_model: { gemma4: { saved_total: 100 }, junk: 'nope', sonnet: 250 },
        time_series: [{ saved_total: 1 }, 'garbage']
      }
    })

    expect(parsed.dimensions.byModel).toEqual([
      { key: 'gemma4', savedPercent: null, savedTotal: 100 },
      { key: 'sonnet', savedPercent: null, savedTotal: 250 }
    ])
    // A day-less time_series point is dropped, never invented.
    expect(parsed.dimensions.timeSeries).toEqual([])
  })

  it('reports empty dimensions when the report has none (UI skips the sections)', () => {
    expect(parseSavingsReport({ totals: { spent: 1 } }).dimensions).toEqual({
      byModel: [],
      byProof: [],
      timeSeries: []
    })
  })
})

describe('cumulativeFromTimeSeries', () => {
  it('builds an ascending cumulative curve from daily saved totals', () => {
    const series = cumulativeFromTimeSeries([
      { actualTotal: null, baselineTotal: null, day: '2026-07-06', savedPercent: null, savedTotal: 100 },
      { actualTotal: null, baselineTotal: null, day: '2026-07-05', savedPercent: null, savedTotal: 50 },
      { actualTotal: null, baselineTotal: null, day: 'bad-date', savedPercent: null, savedTotal: 5 },
      { actualTotal: null, baselineTotal: null, day: '2026-07-07', savedPercent: null, savedTotal: null }
    ])

    expect(series.map(point => point.cumulativeSaved)).toEqual([50, 150])
  })
})
