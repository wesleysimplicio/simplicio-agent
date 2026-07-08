import { useCallback, useEffect, useRef, useState } from 'react'

import {
  type CockpitOutcome,
  controlMcpDaemon,
  fetchDoctorRun,
  fetchMcpDaemonStatus,
  fetchMemoryStatus,
  fetchSavingsReport,
  fetchSavingsSessions,
  getBridgeCapabilities
} from './bridge'
import {
  type CockpitSession,
  type DoctorInfo,
  type MemoryInfo,
  parseDoctor,
  parseMemoryStatus,
  parseSessions
} from './cockpit'
import { parseSavingsReport, type ParsedSavingsReport } from './parse'
import type { McpDaemonStatus } from './types'

const AUTO_REFRESH_MS = 30_000

export type SavingsDataState =
  | { status: 'error'; error: string }
  | { status: 'loading' }
  | { status: 'ok'; parsed: ParsedSavingsReport }
  | { status: 'unavailable' }

/**
 * Per-surface state. 'loading' = the method exists and its fetch is in
 * flight (renders as a "checking" skeleton, NEVER as "bridge missing");
 * 'unavailable' = the method genuinely is not exposed by this build
 * (synchronous typeof check, no fetch attempted); 'error' = a fetch actually
 * resolved with an error.
 */
export type CockpitState<T> =
  | { status: 'error'; error: string }
  | { status: 'loading' }
  | { status: 'ok'; data: T }
  | { status: 'unavailable' }

export interface ParsedSessions {
  sessions: CockpitSession[]
  skipped: number
  sources: string[]
}

/** Daemon control surface for the MCP card. `canControl` reflects the sync
 * capability probe; `error` is the real message from a failed action. */
export interface McpControl {
  canControl: boolean
  error: null | string
  pending: boolean
  start: () => void
  stop: () => void
}

export interface UseSavingsDataResult {
  doctor: CockpitState<DoctorInfo>
  mcp: CockpitState<McpDaemonStatus>
  mcpControl: McpControl
  memory: CockpitState<MemoryInfo>
  refresh: () => void
  refreshing: boolean
  sessions: CockpitState<ParsedSessions>
  state: SavingsDataState
}

/** Initial state for a surface: loading when its method exists, else an
 * honest unavailable — decided synchronously, before any fetch. */
export function initialSurfaceState<T>(methodExists: boolean): CockpitState<T> {
  return methodExists ? { status: 'loading' } : { status: 'unavailable' }
}

/**
 * Stale-while-revalidate merge: a resolved outcome replaces the surface
 * state, EXCEPT that a surface which already has good data never regresses —
 * a 'loading' or 'unavailable' outcome after data was shown keeps the old
 * data (the method cannot honestly vanish mid-session; regressing would
 * blank a resolved card). Errors are resolved facts and do replace data.
 */
export function mergeSurfaceState<T>(prev: CockpitState<T>, next: CockpitState<T>): CockpitState<T> {
  if (prev.status === 'ok' && (next.status === 'unavailable' || next.status === 'loading')) {
    return prev
  }

  return next
}

function outcomeToState<T>(outcome: CockpitOutcome<unknown>, parse: (payload: unknown) => T): CockpitState<T> {
  if (outcome.kind === 'unavailable') {
    return { status: 'unavailable' }
  }

  if (outcome.kind === 'error') {
    return { error: outcome.error, status: 'error' }
  }

  return { data: parse(outcome.payload), status: 'ok' }
}

/**
 * Polls the full cockpit surface (savings report, MCP daemon, doctor, neural
 * memory, ledger sessions) every 30s plus on-demand.
 *
 * Honesty + latency contract:
 * - Surfaces resolve INDEPENDENTLY — each fetch updates its own card the
 *   moment it settles; a slow `doctor` (5-10s IPC) never holds back `memory`
 *   or the MCP chip. No Promise.all barrier on the data path.
 * - In-flight is 'loading' ("checking"), never "bridge missing".
 *   "Unavailable" requires the method to actually not exist (sync typeof
 *   probe, no fetch attempted for it).
 * - Stale-while-revalidate: a refresh keeps showing the last good data (plus
 *   the spinner) until the new result lands; it never regresses a resolved
 *   card to loading/unavailable.
 */
export function useSavingsData(): UseSavingsDataResult {
  const [capabilities] = useState(getBridgeCapabilities)
  const [state, setState] = useState<SavingsDataState>(() =>
    capabilities.savingsReport ? { status: 'loading' } : { status: 'unavailable' }
  )
  const [mcp, setMcp] = useState<CockpitState<McpDaemonStatus>>(() =>
    initialSurfaceState(capabilities.mcpDaemonStatus)
  )
  const [doctor, setDoctor] = useState<CockpitState<DoctorInfo>>(() => initialSurfaceState(capabilities.doctorRun))
  const [memory, setMemory] = useState<CockpitState<MemoryInfo>>(() => initialSurfaceState(capabilities.memoryStatus))
  const [sessions, setSessions] = useState<CockpitState<ParsedSessions>>(() =>
    initialSurfaceState(capabilities.savingsSessions)
  )
  const [refreshing, setRefreshing] = useState(false)
  const requestIdRef = useRef(0)

  const load = useCallback(() => {
    const requestId = requestIdRef.current + 1
    requestIdRef.current = requestId
    setRefreshing(true)

    function settle<T>(
      setter: (updater: (prev: CockpitState<T>) => CockpitState<T>) => void,
      next: CockpitState<T>
    ): void {
      if (requestIdRef.current === requestId) {
        setter(prev => mergeSurfaceState(prev, next))
      }
    }

    // Each surface updates the instant its own IPC call settles.
    const tasks: Promise<unknown>[] = [
      fetchMcpDaemonStatus().then(outcome =>
        settle<McpDaemonStatus>(setMcp, outcomeToState(outcome, payload => payload as McpDaemonStatus))
      ),
      fetchDoctorRun().then(outcome => settle(setDoctor, outcomeToState(outcome, parseDoctor))),
      fetchMemoryStatus().then(outcome => settle(setMemory, outcomeToState(outcome, parseMemoryStatus))),
      fetchSavingsSessions().then(outcome =>
        settle<ParsedSessions>(
          setSessions,
          outcome.kind === 'ok'
            ? {
                data: {
                  sessions: parseSessions(outcome.payload.sessions),
                  skipped: outcome.payload.skipped,
                  sources: outcome.payload.sources
                },
                status: 'ok'
              }
            : outcome.kind === 'error'
              ? { error: outcome.error, status: 'error' }
              : { status: 'unavailable' }
        )
      ),
      fetchSavingsReport().then(outcome => {
        if (requestIdRef.current !== requestId) {
          return
        }

        if (outcome.kind === 'unavailable') {
          // Same no-regress rule as the cards.
          setState(prev => (prev.status === 'ok' ? prev : { status: 'unavailable' }))
        } else if (outcome.kind === 'error') {
          setState({ error: outcome.error, status: 'error' })
        } else {
          setState({ parsed: parseSavingsReport(outcome.report), status: 'ok' })
        }
      })
    ]

    // The refresh spinner runs until every surface settled; the cards resolve
    // one by one above (allSettled so one rejection can't strand the flag).
    void Promise.allSettled(tasks).then(() => {
      if (requestIdRef.current === requestId) {
        setRefreshing(false)
      }
    })
  }, [])

  useEffect(() => {
    load()
    const interval = window.setInterval(() => load(), AUTO_REFRESH_MS)

    return () => window.clearInterval(interval)
  }, [load])

  const [mcpActionPending, setMcpActionPending] = useState(false)
  const [mcpActionError, setMcpActionError] = useState<null | string>(null)

  const runMcpAction = useCallback(async (action: 'start' | 'stop') => {
    setMcpActionPending(true)
    setMcpActionError(null)

    const outcome = await controlMcpDaemon(action)

    if (outcome.kind === 'ok') {
      // The action resolves with the daemon's fresh status — apply it now,
      // then re-fetch once more so a spawn that settles a beat later (pid,
      // restart bookkeeping) is reflected too.
      setMcp(prev => mergeSurfaceState(prev, { data: outcome.payload, status: 'ok' }))
      const refreshed = await fetchMcpDaemonStatus()
      setMcp(prev => mergeSurfaceState(prev, outcomeToState(refreshed, payload => payload as McpDaemonStatus)))
    } else if (outcome.kind === 'error') {
      setMcpActionError(outcome.error)
    } else {
      setMcpActionError('Daemon control is not exposed by this build.')
    }

    setMcpActionPending(false)
  }, [])

  const mcpControl: McpControl = {
    canControl: capabilities.mcpDaemonControl,
    error: mcpActionError,
    pending: mcpActionPending,
    start: () => void runMcpAction('start'),
    stop: () => void runMcpAction('stop')
  }

  return { doctor, mcp, mcpControl, memory, refresh: load, refreshing, sessions, state }
}
