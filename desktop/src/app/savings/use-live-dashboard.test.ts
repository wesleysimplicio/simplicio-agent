import { describe, expect, it } from 'vitest'

import type { ParsedDashboardSummary } from './dashboard-parse'
import { mergeLiveState, type LiveDashboardState } from './use-live-dashboard'

const EMPTY_SUMMARY: ParsedDashboardSummary = {
  byProvider: [],
  byRepo: [],
  generatedAt: null,
  recent: [],
  timeseries: [],
  totals: { baseline: null, costSavedUsd: null, events: null, saved: null, savedPct: null, spent: null }
}

const OK: LiveDashboardState = {
  diff: { changedTotals: new Set(), isNewGeneration: false, newRecentKeys: new Set() },
  status: 'ok',
  summary: EMPTY_SUMMARY,
  updatedAtMs: 1
}

describe('mergeLiveState', () => {
  it('never regresses resolved data to loading/starting/unavailable', () => {
    expect(mergeLiveState(OK, { status: 'loading' })).toBe(OK)
    expect(mergeLiveState(OK, { status: 'starting' })).toBe(OK)
    expect(mergeLiveState(OK, { status: 'unavailable' })).toBe(OK)
  })

  it('accepts a fresh ok result over a previous one', () => {
    const next = { ...OK, updatedAtMs: 2 }

    expect(mergeLiveState(OK, next)).toBe(next)
  })

  it('accepts an error as a resolved fact, replacing prior ok data', () => {
    const errored = { error: 'daemon exited', status: 'error' } as const

    expect(mergeLiveState(OK, errored)).toBe(errored)
  })

  it('passes through freely when there is no prior ok data', () => {
    expect(mergeLiveState({ status: 'loading' }, { status: 'starting' })).toEqual({ status: 'starting' })
    expect(mergeLiveState({ status: 'unavailable' }, { status: 'loading' })).toEqual({ status: 'loading' })
  })
})
