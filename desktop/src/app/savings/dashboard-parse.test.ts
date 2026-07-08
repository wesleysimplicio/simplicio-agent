import { describe, expect, it } from 'vitest'

import { parseDashboardSummary, recentEventKey } from './dashboard-parse'

describe('parseDashboardSummary', () => {
  it('returns an all-empty/null summary for malformed input, never invented figures', () => {
    expect(parseDashboardSummary(null)).toEqual({
      byProvider: [],
      byRepo: [],
      generatedAt: null,
      recent: [],
      timeseries: [],
      totals: { baseline: null, costSavedUsd: null, events: null, saved: null, savedPct: null, spent: null }
    })
    expect(parseDashboardSummary('not an object')).toEqual(parseDashboardSummary(undefined))
    expect(parseDashboardSummary([])).toEqual(parseDashboardSummary(undefined))
  })

  it('parses totals from a nested totals block, snake_case keys', () => {
    const parsed = parseDashboardSummary({
      totals: {
        baseline: 1000,
        cost_saved_usd: 0.42,
        events: 7,
        saved: 600,
        saved_pct: 60,
        spent: 400
      }
    })

    expect(parsed.totals).toEqual({
      baseline: 1000,
      costSavedUsd: 0.42,
      events: 7,
      saved: 600,
      savedPct: 60,
      spent: 400
    })
  })

  it('derives saved and saved_pct from spent+baseline when the report omits them', () => {
    const parsed = parseDashboardSummary({ totals: { baseline: 1000, events: 3, spent: 250 } })

    expect(parsed.totals.saved).toBe(750)
    expect(parsed.totals.savedPct).toBe(75)
  })

  it('falls back to totals living at the top level when there is no nested totals block', () => {
    const parsed = parseDashboardSummary({ baseline: 100, events: 2, saved: 40, spent: 60 })

    expect(parsed.totals).toEqual({ baseline: 100, costSavedUsd: null, events: 2, saved: 40, savedPct: 40, spent: 60 })
  })

  it('parses by_provider / by_repo from an array-of-entries shape', () => {
    const parsed = parseDashboardSummary({
      by_provider: [
        { events: 5, key: 'anthropic', saved: 900, spent: 100 },
        { key: 'deepseek', saved_total: 300 }
      ],
      by_repo: [{ key: 'simplicio-runtime', saved: 500 }]
    })

    expect(parsed.byProvider).toEqual([
      { events: 5, key: 'anthropic', saved: 900, spent: 100 },
      { events: null, key: 'deepseek', saved: 300, spent: null }
    ])
    expect(parsed.byRepo).toEqual([{ events: null, key: 'simplicio-runtime', saved: 500, spent: null }])
  })

  it('parses by_provider from an object-map shape', () => {
    const parsed = parseDashboardSummary({
      by_provider: { anthropic: { saved: 900 }, deepseek: 300 }
    })

    expect(parsed.byProvider).toEqual([
      { events: null, key: 'anthropic', saved: 900, spent: null },
      { events: null, key: 'deepseek', saved: 300, spent: null }
    ])
  })

  it('drops dimension entries with no usable key', () => {
    const parsed = parseDashboardSummary({ by_provider: [{ saved: 900 }, { key: '', saved: 1 }] })

    expect(parsed.byProvider).toEqual([])
  })

  it('parses timeseries buckets and sorts them ascending by time', () => {
    const parsed = parseDashboardSummary({
      timeseries: [
        { bucket: '2026-07-07T10:00:00Z', saved: 20 },
        { bucket: '2026-07-07T08:00:00Z', saved: 10 },
        { bucket: '2026-07-07T09:00:00Z', events: 4, saved: 15, spent: 5 }
      ]
    })

    expect(parsed.timeseries.map(p => p.bucket)).toEqual([
      '2026-07-07T08:00:00Z',
      '2026-07-07T09:00:00Z',
      '2026-07-07T10:00:00Z'
    ])
    expect(parsed.timeseries[1]).toMatchObject({ events: 4, saved: 15, spent: 5 })
  })

  it('keeps report order when bucket labels are unparseable as dates', () => {
    const parsed = parseDashboardSummary({
      timeseries: [{ bucket: 'not-a-date', saved: 1 }, { bucket: 'still-not', saved: 2 }]
    })

    expect(parsed.timeseries.map(p => p.bucket)).toEqual(['not-a-date', 'still-not'])
  })

  it('skips timeseries entries with no bucket label', () => {
    const parsed = parseDashboardSummary({ timeseries: [{ saved: 1 }, { bucket: 'x', saved: 2 }] })

    expect(parsed.timeseries).toHaveLength(1)
  })

  it('parses the recent feed, deriving a stable content key per event', () => {
    const parsed = parseDashboardSummary({
      recent: [
        {
          model: 'claude-sonnet',
          provider: 'anthropic',
          repo: 'simplicio-runtime',
          saved: 120,
          spent: 80,
          task: 'edit file',
          ts: '2026-07-07T12:00:00Z'
        }
      ]
    })

    expect(parsed.recent).toHaveLength(1)
    expect(parsed.recent[0]).toMatchObject({
      model: 'claude-sonnet',
      provider: 'anthropic',
      repo: 'simplicio-runtime',
      saved: 120,
      spent: 80,
      task: 'edit file'
    })
    expect(parsed.recent[0].key).toBe(
      recentEventKey({
        model: 'claude-sonnet',
        provider: 'anthropic',
        repo: 'simplicio-runtime',
        saved: 120,
        spent: 80,
        task: 'edit file',
        ts: '2026-07-07T12:00:00Z'
      })
    )
  })

  it('reads a singular surface string, or joins a surfaces array when singular is absent', () => {
    const single = parseDashboardSummary({ recent: [{ surface: 'edit', ts: '2026-07-07T12:00:00Z' }] })
    const multi = parseDashboardSummary({ recent: [{ surfaces: ['map', 'edit'], ts: '2026-07-07T12:00:00Z' }] })
    const none = parseDashboardSummary({ recent: [{ ts: '2026-07-07T12:00:00Z' }] })

    expect(single.recent[0].surface).toBe('edit')
    expect(multi.recent[0].surface).toBe('map · edit')
    expect(none.recent[0].surface).toBeNull()
  })

  it('two events with identical content fields collide on the same key (documented content-identity tradeoff)', () => {
    const raw = { model: 'm', provider: 'p', saved: 1, spent: 1, task: 't', ts: 'same-ts' }
    const parsed = parseDashboardSummary({ recent: [raw, raw] })

    expect(parsed.recent[0].key).toBe(parsed.recent[1].key)
  })

  it('reads generatedAt from generated_at / generatedAt / as_of', () => {
    expect(parseDashboardSummary({ generated_at: '2026-07-07T12:00:00Z' }).generatedAt).toBe('2026-07-07T12:00:00Z')
    expect(parseDashboardSummary({ generatedAt: '2026-07-07T12:00:00Z' }).generatedAt).toBe('2026-07-07T12:00:00Z')
    expect(parseDashboardSummary({ as_of: '2026-07-07T12:00:00Z' }).generatedAt).toBe('2026-07-07T12:00:00Z')
    expect(parseDashboardSummary({}).generatedAt).toBeNull()
  })
})
