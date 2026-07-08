import { useEffect, useState } from 'react'

import { INITIAL_THRESHOLD_STATE, nextThresholdState, type ThresholdState } from '@/app/savings/cockpit'

function prefersReducedMotion(): boolean {
  return typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches === true
}

export interface ThresholdCrossing {
  /** Value is currently at/above the threshold (drives the persistent glow). */
  active: boolean
  /** Increments on each false→true crossing — use as a React key to mount a
   * one-shot burst. 0 = never crossed. Frozen under prefers-reduced-motion. */
  burstKey: number
}

/**
 * Tracks a value crossing a threshold (default use: savings percent >= 90).
 * The pure state machine lives in cockpit.ts (`nextThresholdState`) so the
 * crossing semantics are unit-tested without React. Under reduced motion the
 * burst never fires (burstKey stays 0) while `active` still reports honestly
 * so the static badge can render.
 */
export function useThresholdCrossing(value: null | number | undefined, threshold = 90): ThresholdCrossing {
  const [state, setState] = useState<ThresholdState>(INITIAL_THRESHOLD_STATE)

  useEffect(() => {
    setState(prev => nextThresholdState(prev, value ?? null, threshold))
  }, [value, threshold])

  return {
    active: state.active,
    burstKey: prefersReducedMotion() ? 0 : state.burstCount
  }
}
