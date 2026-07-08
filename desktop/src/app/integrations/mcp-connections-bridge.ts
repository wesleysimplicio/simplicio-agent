// Thin, defensive wrapper around `window.simplicioSavings.mcpConnections` --
// the live-status complement to `types.ts`'s `editorsDetect`/`mcpRegister`
// (which report static "installed / registered in config" state). Same
// shape/contract as `app/savings/dashboard.ts`'s summary wrapper: every call
// goes through a synchronous capability probe first, so a preload build that
// doesn't expose the method degrades to an honest 'unavailable' outcome
// instead of a crash. The runtime binary itself may also not implement the
// `mcp status` subcommand yet -- that surfaces as the IPC bridge resolving
// `{ok:false, error}`, which this wrapper folds into the same 'error' outcome
// (never invented as 'unavailable' silence -- the real message is preserved).

/** `simplicio mcp status --json`'s payload -- schema owned by the runtime,
 * not stable here. Parsed defensively by `mcp-connections-presentation.ts`. */
export type McpConnectionsRawStatus = unknown

interface McpConnectionsBridgeMethods {
  mcpConnections: () => Promise<{ ok: boolean; status?: McpConnectionsRawStatus; error?: string }>
}

function getSavingsWindow(): Partial<McpConnectionsBridgeMethods> | undefined {
  if (typeof window === 'undefined') {
    return undefined
  }

  const candidate = (window as unknown as { simplicioSavings?: unknown }).simplicioSavings

  return candidate && typeof candidate === 'object' ? (candidate as Partial<McpConnectionsBridgeMethods>) : undefined
}

export interface McpConnectionsCapabilities {
  mcpConnections: boolean
}

/** Synchronous capability probe -- no IPC round trip, so a method that exists
 * starts its surface as 'loading', never as "bridge missing". */
export function getMcpConnectionsCapabilities(): McpConnectionsCapabilities {
  return { mcpConnections: typeof getSavingsWindow()?.mcpConnections === 'function' }
}

export type McpConnectionsOutcome =
  | { kind: 'error'; error: string }
  | { kind: 'ok'; payload: McpConnectionsRawStatus }
  | { kind: 'unavailable' }

export async function fetchMcpConnectionsStatus(): Promise<McpConnectionsOutcome> {
  const w = getSavingsWindow()

  if (typeof w?.mcpConnections !== 'function') {
    return { kind: 'unavailable' }
  }

  try {
    const result = await w.mcpConnections()

    if (result?.ok) {
      return { kind: 'ok', payload: result.status }
    }

    return { error: result?.error || 'Unknown error from mcp status bridge', kind: 'error' }
  } catch (err) {
    return { error: err instanceof Error ? err.message : String(err), kind: 'error' }
  }
}
