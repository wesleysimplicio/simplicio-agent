import { describe, expect, it } from 'vitest'

import { cumulativeSavedSeries, parseSavingsReport } from './parse'

describe('parseSavingsReport', () => {
  it('returns empty, honest defaults for a non-object report', () => {
    expect(parseSavingsReport(null)).toEqual({
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
