import { describe, expect, it } from 'vitest'

import { formatRelativeTime } from './live-format'

describe('formatRelativeTime', () => {
  it('returns null for an unknown timestamp', () => {
    expect(formatRelativeTime(null, 1_000)).toBeNull()
  })

  it('returns null for non-finite input', () => {
    expect(formatRelativeTime(Number.NaN, 1_000)).toBeNull()
    expect(formatRelativeTime(0, Number.POSITIVE_INFINITY)).toBeNull()
  })

  it('returns null instead of a negative delta (clock skew / future timestamp)', () => {
    expect(formatRelativeTime(2_000, 1_000)).toBeNull()
  })

  it('reports "now" for anything under a second old', () => {
    expect(formatRelativeTime(1_000, 1_000)).toBe('now')
    expect(formatRelativeTime(500, 1_400)).toBe('now')
  })

  it('buckets seconds', () => {
    expect(formatRelativeTime(0, 1_000)).toBe('1s')
    expect(formatRelativeTime(0, 45_000)).toBe('45s')
    expect(formatRelativeTime(0, 59_999)).toBe('59s')
  })

  it('buckets minutes once past 60s', () => {
    expect(formatRelativeTime(0, 60_000)).toBe('1m')
    expect(formatRelativeTime(0, 90_000)).toBe('1m')
    expect(formatRelativeTime(0, 59 * 60_000)).toBe('59m')
  })

  it('buckets hours once past 60m', () => {
    expect(formatRelativeTime(0, 60 * 60_000)).toBe('1h')
    expect(formatRelativeTime(0, 5 * 60 * 60_000)).toBe('5h')
  })
})
