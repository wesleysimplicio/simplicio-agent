// Presentation formatting specific to Live Activity's real-time surface:
// a relative-time label ("agora" / "12s atrás" / "3m atrás") for the "AO
// VIVO" header, recomputed on a ticking clock rather than once. Pure
// function of two epoch-ms timestamps — no `Date.now()` inside, so it
// unit-tests deterministically.

/**
 * `updatedAtMs` relative to `nowMs`, in whole-second/minute/hour buckets.
 * Negative or non-finite input (clock skew, not-yet-loaded) falls back to
 * `null` rather than a nonsensical "-3s ago". Callers re-invoke this on a
 * tick (e.g. every 1s) with a fresh `nowMs` to keep the label live.
 */
export function formatRelativeTime(updatedAtMs: null | number, nowMs: number): null | string {
  if (updatedAtMs === null || !Number.isFinite(updatedAtMs) || !Number.isFinite(nowMs)) {
    return null
  }

  const deltaMs = nowMs - updatedAtMs

  if (deltaMs < 0) {
    return null
  }

  if (deltaMs < 1000) {
    return 'now'
  }

  const seconds = Math.floor(deltaMs / 1000)

  if (seconds < 60) {
    return `${seconds}s`
  }

  const minutes = Math.floor(seconds / 60)

  if (minutes < 60) {
    return `${minutes}m`
  }

  const hours = Math.floor(minutes / 60)

  return `${hours}h`
}
