import { describe, expect, it } from 'vitest'

import { mergeMcpConnectionsState, type McpConnectionsState } from './use-mcp-connections'

const OK: McpConnectionsState = { connections: [], generatedAtMs: null, status: 'ok', updatedAtMs: 1 }

describe('mergeMcpConnectionsState', () => {
  it('never regresses resolved connections data to a transient loading poll', () => {
    expect(mergeMcpConnectionsState(OK, { status: 'loading' })).toBe(OK)
  })

  it('accepts a fresh ok result over a previous one', () => {
    const next: McpConnectionsState = { ...OK, updatedAtMs: 2 }

    expect(mergeMcpConnectionsState(OK, next)).toBe(next)
  })

  // 'unavailable' is a resolved, honest fact (bridge missing, or a real
  // backend error like "unknown mcp subcommand 'status'") -- it must replace
  // prior ok data, never be masked behind a stale success.
  it('accepts unavailable as a resolved fact, replacing prior ok data', () => {
    const unavailable: McpConnectionsState = { error: 'unknown mcp subcommand', status: 'unavailable' }

    expect(mergeMcpConnectionsState(OK, unavailable)).toBe(unavailable)
  })

  it('passes through freely when there is no prior ok data', () => {
    expect(mergeMcpConnectionsState({ status: 'loading' }, { error: 'x', status: 'unavailable' })).toEqual({
      error: 'x',
      status: 'unavailable'
    })
  })
})
