// Defensive, pure parsing + presentation for `simplicio mcp status --json`
// (the live MCP-client-connections surface). Same honesty contract as
// `app/savings/dashboard-parse.ts`: every extractor tolerates a missing or
// malformed field by returning `null`/`false`/`[]` rather than guessing, and
// nothing here touches React/DOM -- everything unit-tests with plain
// objects. `null` on a field means "the runtime didn't report this", never
// "assume zero/false".

import type { IntegrationEditorInfo } from './types'

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function numOrNull(value: unknown): null | number {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value
  }

  if (typeof value === 'string' && value.trim() !== '') {
    const parsed = Number(value)

    return Number.isFinite(parsed) ? parsed : null
  }

  return null
}

function strOrNull(value: unknown): null | string {
  return typeof value === 'string' && value.trim() !== '' ? value : null
}

function pick(record: Record<string, unknown>, keys: readonly string[]): unknown {
  for (const key of keys) {
    if (record[key] !== undefined && record[key] !== null) {
      return record[key]
    }
  }

  return undefined
}

/** Unix seconds -> epoch ms, honest null on anything unparsable. The wire
 * contract is `connected_at`/`last_tool_call_at` as unix seconds (not ms). */
function secondsToMs(value: unknown): null | number {
  const seconds = numOrNull(value)

  return seconds === null ? null : seconds * 1000
}

function toolsUsedOrEmpty(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return []
  }

  return value.filter((v): v is string => typeof v === 'string' && v.trim() !== '')
}

// ---------------------------------------------------------------------------
// One live connection
// ---------------------------------------------------------------------------

export interface McpLiveConnection {
  pid: null | number
  clientName: null | string
  clientVersion: null | string
  repo: null | string
  connectedAtMs: null | number
  alive: boolean
  lastToolCallAtMs: null | number
  toolsUsed: string[]
}

function parseConnection(raw: unknown): McpLiveConnection | null {
  if (!isRecord(raw)) {
    return null
  }

  return {
    alive: raw.alive === true,
    clientName: strOrNull(pick(raw, ['client_name', 'clientName'])),
    clientVersion: strOrNull(pick(raw, ['client_version', 'clientVersion'])),
    connectedAtMs: secondsToMs(pick(raw, ['connected_at', 'connectedAt'])),
    lastToolCallAtMs: secondsToMs(pick(raw, ['last_tool_call_at', 'lastToolCallAt'])),
    pid: numOrNull(raw.pid),
    repo: strOrNull(raw.repo),
    toolsUsed: toolsUsedOrEmpty(pick(raw, ['tools_used', 'toolsUsed']))
  }
}

// ---------------------------------------------------------------------------
// Top-level status
// ---------------------------------------------------------------------------

export interface ParsedMcpStatus {
  connections: McpLiveConnection[]
  /** `generated_at` (unix seconds -> ms), null when the runtime didn't report one. */
  generatedAtMs: null | number
}

const EMPTY_STATUS: ParsedMcpStatus = { connections: [], generatedAtMs: null }

export function parseMcpStatus(raw: unknown): ParsedMcpStatus {
  if (!isRecord(raw)) {
    return EMPTY_STATUS
  }

  const rawConnections = pick(raw, ['connections'])
  const connections = Array.isArray(rawConnections)
    ? rawConnections.map(parseConnection).filter((c): c is McpLiveConnection => c !== null)
    : []

  return {
    connections,
    generatedAtMs: secondsToMs(pick(raw, ['generated_at', 'generatedAt']))
  }
}

// ---------------------------------------------------------------------------
// Display ordering: alive first (most-recently-connected first within that
// tier), then dead connections (most-recently-active first). Mirrors
// `editor-presentation.ts`'s `sortEditorsForDisplay` rank-then-tiebreak shape
// so a poll refresh doesn't reshuffle the list gratuitously.
// ---------------------------------------------------------------------------

export function sortConnectionsForDisplay(connections: McpLiveConnection[]): McpLiveConnection[] {
  return [...connections].sort((a, b) => {
    if (a.alive !== b.alive) {
      return a.alive ? -1 : 1
    }

    const aTime = a.connectedAtMs ?? -Infinity
    const bTime = b.connectedAtMs ?? -Infinity

    if (aTime !== bTime) {
      return bTime - aTime
    }

    return (a.clientName ?? '').localeCompare(b.clientName ?? '')
  })
}

// ---------------------------------------------------------------------------
// Relative "connected Xm ago" label -- same bucket shape as
// `editor-presentation.ts`'s `formatDaemonUptime`, adapted for an epoch-ms
// input instead of an ISO string (the wire format here is unix seconds).
// Returns null for a missing/unparsable/future timestamp so the caller can
// hide the clause instead of rendering garbage.
// ---------------------------------------------------------------------------

export function formatConnectionElapsed(sinceMs: null | number, nowMs: number = Date.now()): null | string {
  if (sinceMs === null || !Number.isFinite(sinceMs)) {
    return null
  }

  const deltaSec = Math.floor((nowMs - sinceMs) / 1000)

  if (deltaSec < 0) {
    return null
  }

  if (deltaSec < 60) {
    return `${deltaSec}s`
  }

  const minutes = Math.floor(deltaSec / 60)

  if (minutes < 60) {
    return `${minutes}m`
  }

  const hours = Math.floor(minutes / 60)
  const remMinutes = minutes % 60

  if (hours < 24) {
    return remMinutes ? `${hours}h ${remMinutes}m` : `${hours}h`
  }

  const days = Math.floor(hours / 24)
  const remHours = hours % 24

  return remHours ? `${days}d ${remHours}h` : `${days}d`
}

// ---------------------------------------------------------------------------
// Cross-reference with the static Editors & agents list: a live connection's
// `client_name` (as reported by the MCP handshake, e.g. "Claude Code",
// "claude-code", "Cursor") is matched against a known editor's id/name by a
// normalized-string comparison -- never a guess dressed as a match. Used to
// put a "live now" badge on an EditorCard whose editor has a matching alive
// connection.
// ---------------------------------------------------------------------------

function normalizeForMatch(value: string): string {
  return value.trim().toLowerCase().replace(/[\s_-]+/g, '')
}

export function matchesEditor(
  connection: Pick<McpLiveConnection, 'clientName'>,
  editor: Pick<IntegrationEditorInfo, 'id' | 'name'>
): boolean {
  if (!connection.clientName) {
    return false
  }

  const client = normalizeForMatch(connection.clientName)

  return client === normalizeForMatch(editor.id) || client === normalizeForMatch(editor.name)
}

/** First alive connection matching `editor`, or null. Used by the Integrations
 * screen to badge an EditorCard as "live now". */
export function findLiveConnectionForEditor(
  connections: McpLiveConnection[],
  editor: Pick<IntegrationEditorInfo, 'id' | 'name'>
): McpLiveConnection | null {
  return connections.find(c => c.alive && matchesEditor(c, editor)) ?? null
}
