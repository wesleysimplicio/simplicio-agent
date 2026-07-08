import { useCallback, useEffect, useRef, useState } from 'react'

import { fetchMcpConnectionsStatus, getMcpConnectionsCapabilities } from './mcp-connections-bridge'
import { type McpLiveConnection, parseMcpStatus, sortConnectionsForDisplay } from './mcp-connections-presentation'

// Short cadence (3-4s) so a newly-connected MCP client, or a tool call it
// just made, shows up close to real time -- separate from (and faster than)
// `use-integrations-data.ts`'s 20s poll of the static installed/registered
// state, which doesn't need to feel "live".
const POLL_MS = 3_500

/** Fixed technical fallback for "the bridge doesn't expose this method at
 * all" (an older preload build) -- distinct from a real backend error string,
 * but surfaced through the same 'unavailable' state/detail so the UI never
 * needs a fourth branch for it. */
export const MCP_CONNECTIONS_BRIDGE_MISSING = 'simplicio:mcp-connections bridge not available in this build'

export type McpConnectionsState =
  | { status: 'loading' }
  | { status: 'ok'; connections: McpLiveConnection[]; generatedAtMs: null | number; updatedAtMs: number }
  | { status: 'unavailable'; error: string }

/** Stale-while-revalidate merge, same regress rule as `useLiveDashboard`'s
 * `mergeLiveState`: once real data has rendered, an in-flight poll
 * ('loading') never blanks it. An 'unavailable' (bridge missing or a real
 * backend error) IS a resolved fact and does replace -- never masked. */
export function mergeMcpConnectionsState(prev: McpConnectionsState, next: McpConnectionsState): McpConnectionsState {
  if (prev.status === 'ok' && next.status === 'loading') {
    return prev
  }

  return next
}

export interface UseMcpConnectionsResult {
  refresh: () => void
  state: McpConnectionsState
}

export function useMcpConnections(): UseMcpConnectionsResult {
  const [capabilities] = useState(getMcpConnectionsCapabilities)
  const [state, setState] = useState<McpConnectionsState>(() =>
    capabilities.mcpConnections ? { status: 'loading' } : { error: MCP_CONNECTIONS_BRIDGE_MISSING, status: 'unavailable' }
  )
  const cancelledRef = useRef(false)

  const poll = useCallback(async () => {
    const outcome = await fetchMcpConnectionsStatus()

    if (cancelledRef.current) {
      return
    }

    if (outcome.kind === 'unavailable') {
      setState(prev => mergeMcpConnectionsState(prev, { error: MCP_CONNECTIONS_BRIDGE_MISSING, status: 'unavailable' }))

      return
    }

    if (outcome.kind === 'error') {
      setState(prev => mergeMcpConnectionsState(prev, { error: outcome.error, status: 'unavailable' }))

      return
    }

    const parsed = parseMcpStatus(outcome.payload)
    setState(prev =>
      mergeMcpConnectionsState(prev, {
        connections: sortConnectionsForDisplay(parsed.connections),
        generatedAtMs: parsed.generatedAtMs,
        status: 'ok',
        updatedAtMs: Date.now()
      })
    )
  }, [])

  useEffect(() => {
    if (!capabilities.mcpConnections) {
      return
    }

    cancelledRef.current = false
    void poll()

    const tick = () => {
      if (document.visibilityState === 'visible') {
        void poll()
      }
    }

    const intervalId = window.setInterval(tick, POLL_MS)
    document.addEventListener('visibilitychange', tick)

    return () => {
      cancelledRef.current = true
      window.clearInterval(intervalId)
      document.removeEventListener('visibilitychange', tick)
    }
  }, [capabilities.mcpConnections, poll])

  return { refresh: () => void poll(), state }
}
