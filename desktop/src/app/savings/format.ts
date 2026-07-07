// Presentation-only formatting for the savings panel. Every function accepts
// `null` (unknown field) and returns the literal em dash — never a fabricated
// number.

const UNKNOWN = '—'

export function formatTokens(value: null | number): string {
  if (value === null) {
    return UNKNOWN
  }

  const abs = Math.abs(value)
  const sign = value < 0 ? '-' : ''

  if (abs >= 1_000_000) {
    return `${sign}${(abs / 1_000_000).toFixed(1)}M`
  }

  if (abs >= 1_000) {
    return `${sign}${(abs / 1_000).toFixed(1)}K`
  }

  return `${sign}${abs.toLocaleString()}`
}

export function formatExactTokens(value: null | number): string {
  return value === null ? UNKNOWN : Math.round(value).toLocaleString()
}

export function formatPct(value: null | number): string {
  return value === null ? UNKNOWN : `${Math.round(value)}%`
}

export function formatTimestamp(value: null | string): string {
  if (!value) {
    return UNKNOWN
  }

  const ms = /^\d+$/.test(value.trim()) ? (Number(value) > 1e12 ? Number(value) : Number(value) * 1000) : Date.parse(value)

  if (!Number.isFinite(ms)) {
    return value
  }

  return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(ms))
}
