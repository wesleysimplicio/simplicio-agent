import { useCallback, useEffect, useRef, useState } from 'react'

import { fetchMcpDaemonStatus, fetchSavingsReport, isSavingsBridgeAvailable } from './bridge'
import { parseSavingsReport, type ParsedSavingsReport } from './parse'
import type { McpDaemonStatus } from './types'

const AUTO_REFRESH_MS = 30_000

export type SavingsDataState =
  | { status: 'error'; error: string }
  | { status: 'loading' }
  | { status: 'ok'; parsed: ParsedSavingsReport }
  | { status: 'unavailable' }

export interface UseSavingsDataResult {
  mcpStatus: McpDaemonStatus | null
  refresh: () => void
  refreshing: boolean
  state: SavingsDataState
}

/**
 * Polls `window.simplicioSavings` every 30s plus on-demand. Every state
 * transition is explicit (loading/ok/error/unavailable) so the view never has
 * to guess whether an empty report means "no data yet" or "bridge missing".
 */
export function useSavingsData(): UseSavingsDataResult {
  const [state, setState] = useState<SavingsDataState>(() =>
    isSavingsBridgeAvailable() ? { status: 'loading' } : { status: 'unavailable' }
  )
  const [mcpStatus, setMcpStatus] = useState<McpDaemonStatus | null>(null)
  const [refreshing, setRefreshing] = useState(false)
  const requestIdRef = useRef(0)

  const load = useCallback(async () => {
    const requestId = requestIdRef.current + 1
    requestIdRef.current = requestId
    setRefreshing(true)

    const [reportOutcome, status] = await Promise.all([fetchSavingsReport(), fetchMcpDaemonStatus()])

    if (requestIdRef.current !== requestId) {
      return
    }

    setMcpStatus(status)

    if (reportOutcome.kind === 'unavailable') {
      setState({ status: 'unavailable' })
    } else if (reportOutcome.kind === 'error') {
      setState({ error: reportOutcome.error, status: 'error' })
    } else {
      setState({ parsed: parseSavingsReport(reportOutcome.report), status: 'ok' })
    }

    setRefreshing(false)
  }, [])

  useEffect(() => {
    void load()
    const interval = window.setInterval(() => void load(), AUTO_REFRESH_MS)

    return () => window.clearInterval(interval)
  }, [load])

  return { mcpStatus, refresh: () => void load(), refreshing, state }
}
