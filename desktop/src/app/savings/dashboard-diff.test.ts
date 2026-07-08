import { describe, expect, it } from 'vitest'

import { diffDashboardSummary } from './dashboard-diff'
import type { ParsedDashboardSummary } from './dashboard-parse'

const EMPTY_TOTALS = { baseline: null, costSavedUsd: null, events: null, saved: null, savedPct: null, spent: null }

function summary(overrides: Partial<ParsedDashboardSummary> = {}): ParsedDashboardSummary {
  return {
    byProvider: [],
    byRepo: [],
    generatedAt: null,
    recent: [],
    timeseries: [],
    totals: EMPTY_TOTALS,
    ...overrides
  }
}

describe('diffDashboardSummary', () => {
  it('reports nothing changed and no new generation on first load (prev is null)', () => {
    const diff = diffDashboardSummary(null, summary({ totals: { ...EMPTY_TOTALS, saved: 100 } }))

    expect(diff.isNewGeneration).toBe(false)
    expect(diff.changedTotals.size).toBe(0)
    expect(diff.newRecentKeys.size).toBe(0)
  })

  it('detects a new generation via generatedAt changing', () => {
    const prev = summary({ generatedAt: '2026-07-07T12:00:00Z' })
    const next = summary({ generatedAt: '2026-07-07T12:00:03Z' })

    expect(diffDashboardSummary(prev, next).isNewGeneration).toBe(true)
  })

  it('does not flag a new generation when generatedAt is unchanged', () => {
    const prev = summary({ generatedAt: '2026-07-07T12:00:00Z', totals: { ...EMPTY_TOTALS, saved: 10 } })
    const next = summary({ generatedAt: '2026-07-07T12:00:00Z', totals: { ...EMPTY_TOTALS, saved: 10 } })

    expect(diffDashboardSummary(prev, next).isNewGeneration).toBe(false)
  })

  it('falls back to the newest recent-feed key when generatedAt is absent', () => {
    const prev = summary({ recent: [{ ...emptyEvent(), key: 'a' }] })
    const next = summary({ recent: [{ ...emptyEvent(), key: 'b' }, { ...emptyEvent(), key: 'a' }] })

    expect(diffDashboardSummary(prev, next).isNewGeneration).toBe(true)
  })

  it('falls back to totals.events when there is no generatedAt or recent feed', () => {
    const prev = summary({ totals: { ...EMPTY_TOTALS, events: 5 } })
    const same = summary({ totals: { ...EMPTY_TOTALS, events: 5 } })
    const changed = summary({ totals: { ...EMPTY_TOTALS, events: 6 } })

    expect(diffDashboardSummary(prev, same).isNewGeneration).toBe(false)
    expect(diffDashboardSummary(prev, changed).isNewGeneration).toBe(true)
  })

  it('never claims a new generation when both summaries have no fingerprint at all', () => {
    expect(diffDashboardSummary(summary(), summary()).isNewGeneration).toBe(false)
  })

  it('reports exactly which totals fields changed', () => {
    const prev = summary({ totals: { baseline: 1000, costSavedUsd: 0.1, events: 5, saved: 500, savedPct: 50, spent: 500 } })
    const next = summary({ totals: { baseline: 1000, costSavedUsd: 0.1, events: 6, saved: 600, savedPct: 60, spent: 400 } })

    const diff = diffDashboardSummary(prev, next)

    expect(diff.changedTotals).toEqual(new Set(['events', 'saved', 'savedPct', 'spent']))
  })

  it('reports no changed totals when nothing moved', () => {
    const totals = { baseline: 1000, costSavedUsd: 0.1, events: 5, saved: 500, savedPct: 50, spent: 500 }
    const diff = diffDashboardSummary(summary({ totals }), summary({ totals: { ...totals } }))

    expect(diff.changedTotals.size).toBe(0)
  })

  it('reports newRecentKeys as exactly the keys present in next but absent from prev', () => {
    const prev = summary({ recent: [{ ...emptyEvent(), key: 'a' }, { ...emptyEvent(), key: 'b' }] })
    const next = summary({
      recent: [{ ...emptyEvent(), key: 'c' }, { ...emptyEvent(), key: 'a' }, { ...emptyEvent(), key: 'b' }]
    })

    expect(diffDashboardSummary(prev, next).newRecentKeys).toEqual(new Set(['c']))
  })

  it('reports an empty newRecentKeys when the feed is unchanged', () => {
    const recent = [{ ...emptyEvent(), key: 'a' }]

    expect(diffDashboardSummary(summary({ recent }), summary({ recent: [...recent] })).newRecentKeys.size).toBe(0)
  })
})

function emptyEvent() {
  return {
    key: '',
    model: null,
    provider: null,
    repo: null,
    saved: null,
    spent: null,
    surface: null,
    task: null,
    timestampMs: null,
    ts: null
  }
}
