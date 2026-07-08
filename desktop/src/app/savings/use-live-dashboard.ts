import { useCallback, useEffect, useRef, useState } from 'react'

import { controlDashboard, fetchDashboardStatus, fetchDashboardSummary, getDashboardCapabilities } from './dashboard'
import { diffDashboardSummary, type DashboardDiff } from './dashboard-diff'
import { parseDashboardSummary, type ParsedDashboardSummary } from './dashboard-parse'

const POLL_MS = 3_000

export type LiveDashboardState =
  | { status: 'error'; error: string }
  | { status: 'loading' }
  | { status: 'ok'; diff: DashboardDiff; summary: ParsedDashboardSummary; updatedAtMs: number }
  | { status: 'starting' }
  | { status: 'unavailable' }

/**
 * Stale-while-revalidate merge, same regress rule as the cockpit's
 * `mergeSurfaceState`: once real data has rendered, an in-flight poll
 * ('loading'/'starting') or a capability that (impossibly) vanished
 * ('unavailable') never blanks it. An 'error' IS a resolved fact and does
 * replace — the retry button exists precisely for that honest case.
 */
export function mergeLiveState(prev: LiveDashboardState, next: LiveDashboardState): LiveDashboardState {
  if (prev.status === 'ok' && (next.status === 'loading' || next.status === 'starting' || next.status === 'unavailable')) {
    return prev
  }

  return next
}

export interface UseLiveDashboardResult {
  state: LiveDashboardState
  /** True once an automatic or manual dashboardStart() attempt is in flight. */
  starting: boolean
  /** Re-invokes dashboardStart() (when exposed) then re-polls the summary —
   * the "Try again" action for the honest error state. */
  retry: () => void
}

export function useLiveDashboard(): UseLiveDashboardResult {
  const [capabilities] = useState(getDashboardCapabilities)
  const [state, setState] = useState<LiveDashboardState>(() =>
    capabilities.dashboardSummary ? { status: 'loading' } : { status: 'unavailable' }
  )
  const [starting, setStarting] = useState(false)

  // Persists across transient 'error' polls so a recovering feed still
  // diffs against the last real data instead of treating everything as
  // "new" again — the flash/slide-in is about what actually changed, not
  // about whether a poll in between happened to fail.
  const lastSummaryRef = useRef<null | ParsedDashboardSummary>(null)
  const cancelledRef = useRef(false)

  const pollSummary = useCallback(async () => {
    const outcome = await fetchDashboardSummary({ group: 'hour' })

    if (cancelledRef.current) {
      return
    }

    if (outcome.kind === 'unavailable') {
      setState(prev => mergeLiveState(prev, { status: 'unavailable' }))

      return
    }

    if (outcome.kind === 'error') {
      setState(prev => mergeLiveState(prev, { error: outcome.error, status: 'error' }))

      return
    }

    const summary = parseDashboardSummary(outcome.payload)
    const diff = diffDashboardSummary(lastSummaryRef.current, summary)

    lastSummaryRef.current = summary
    setState(prev => mergeLiveState(prev, { diff, status: 'ok', summary, updatedAtMs: Date.now() }))
    // eslint-disable-next-line react-hooks/exhaustive-deps -- refs are not reactive deps
  }, [])

  const attemptStart = useCallback(async () => {
    if (!capabilities.dashboardControl) {
      return
    }

    setStarting(true)
    setState(prev => mergeLiveState(prev, { status: 'starting' }))
    await controlDashboard('start')
    setStarting(false)
    // eslint-disable-next-line react-hooks/exhaustive-deps -- capabilities is fixed for the component's lifetime
  }, [])

  useEffect(() => {
    if (!capabilities.dashboardSummary) {
      return
    }

    cancelledRef.current = false
    let startAttempted = false

    async function bootstrap() {
      if (capabilities.dashboardStatus) {
        const statusOutcome = await fetchDashboardStatus()

        if (cancelledRef.current) {
          return
        }

        if (statusOutcome.kind === 'ok' && !statusOutcome.payload.running && capabilities.dashboardControl && !startAttempted) {
          startAttempted = true
          await attemptStart()

          if (cancelledRef.current) {
            return
          }
        }
      }

      await pollSummary()
    }

    void bootstrap()
    const interval = window.setInterval(() => void pollSummary(), POLL_MS)

    return () => {
      cancelledRef.current = true
      window.clearInterval(interval)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- capabilities/attemptStart/pollSummary are stable for the component's lifetime
  }, [])

  const retry = useCallback(() => {
    void (async () => {
      if (capabilities.dashboardControl) {
        await attemptStart()
      }

      await pollSummary()
    })()
    // eslint-disable-next-line react-hooks/exhaustive-deps -- capabilities/attemptStart/pollSummary are stable for the component's lifetime
  }, [])

  return { retry, starting, state }
}
