import { useEffect, useRef, useState } from 'react'

const DURATION_MS = 900

function prefersReducedMotion(): boolean {
  return typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches === true
}

// Quintic ease-out — quick start, soft settle. Matches the app's other
// entrance easings (see `useEnterAnimation`'s cubic-bezier) without importing
// a curve library.
function easeOutQuint(t: number): number {
  return 1 - (1 - t) ** 5
}

/**
 * Animates a numeric value from its previous committed value to `target` via
 * requestAnimationFrame. Returns the in-flight display value — never the
 * unrounded target mid-flight, so the caller can format it directly.
 *
 * `null`/`undefined` targets (an honestly-unknown metric) are passed through
 * immediately with no animation — there is nothing to count up to.
 */
export function useCountUp(target: null | number | undefined, durationMs = DURATION_MS): null | number {
  const [display, setDisplay] = useState<null | number>(target ?? null)
  const fromRef = useRef(0)
  const rafRef = useRef<null | number>(null)

  useEffect(() => {
    if (rafRef.current !== null) {
      cancelAnimationFrame(rafRef.current)
      rafRef.current = null
    }

    if (target === null || target === undefined) {
      setDisplay(null)

      return
    }

    if (prefersReducedMotion()) {
      setDisplay(target)
      fromRef.current = target

      return
    }

    const from = fromRef.current
    const delta = target - from
    const start = performance.now()

    if (delta === 0) {
      setDisplay(target)

      return
    }

    const tick = (now: number) => {
      const elapsed = now - start
      const progress = Math.min(1, elapsed / durationMs)
      const eased = easeOutQuint(progress)

      setDisplay(from + delta * eased)

      if (progress < 1) {
        rafRef.current = requestAnimationFrame(tick)
      } else {
        fromRef.current = target
      }
    }

    rafRef.current = requestAnimationFrame(tick)

    return () => {
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current)
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- fromRef/rafRef are refs, not reactive deps
  }, [target, durationMs])

  return display
}
