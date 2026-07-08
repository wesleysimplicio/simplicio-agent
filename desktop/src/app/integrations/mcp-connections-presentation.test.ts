import { describe, expect, it } from 'vitest'

import {
  findLiveConnectionForEditor,
  formatConnectionElapsed,
  matchesEditor,
  parseMcpStatus,
  sortConnectionsForDisplay
} from './mcp-connections-presentation'

describe('parseMcpStatus', () => {
  it('returns an empty status for a non-object payload', () => {
    expect(parseMcpStatus(null)).toEqual({ connections: [], generatedAtMs: null })
    expect(parseMcpStatus(undefined)).toEqual({ connections: [], generatedAtMs: null })
    expect(parseMcpStatus('not an object')).toEqual({ connections: [], generatedAtMs: null })
  })

  it('returns an empty connections array when connections is missing or not an array', () => {
    expect(parseMcpStatus({ schema: 'simplicio.mcp-status/v1' }).connections).toEqual([])
    expect(parseMcpStatus({ connections: 'nope' }).connections).toEqual([])
  })

  it('extracts every documented field from the real wire shape (snake_case, unix seconds)', () => {
    const parsed = parseMcpStatus({
      connections: [
        {
          alive: true,
          client_name: 'Claude Code',
          client_version: '2.1.0',
          connected_at: 1751990400,
          last_tool_call_at: 1751990460,
          pid: 4242,
          repo: 'wesleysimplicio/simplicio-agent',
          tools_used: ['edit', 'read']
        }
      ],
      generated_at: 1751990500
    })

    expect(parsed.generatedAtMs).toBe(1751990500 * 1000)
    expect(parsed.connections).toEqual([
      {
        alive: true,
        clientName: 'Claude Code',
        clientVersion: '2.1.0',
        connectedAtMs: 1751990400 * 1000,
        lastToolCallAtMs: 1751990460 * 1000,
        pid: 4242,
        repo: 'wesleysimplicio/simplicio-agent',
        toolsUsed: ['edit', 'read']
      }
    ])
  })

  // The honesty rule: a field the runtime didn't report becomes `null`
  // (or `false`/`[]` for its typed default), never a fabricated guess.
  it('is honest about missing fields — null/false/empty, never invented', () => {
    const parsed = parseMcpStatus({ connections: [{}] })

    expect(parsed.connections).toEqual([
      {
        alive: false,
        clientName: null,
        clientVersion: null,
        connectedAtMs: null,
        lastToolCallAtMs: null,
        pid: null,
        repo: null,
        toolsUsed: []
      }
    ])
  })

  // Captured 2026-07-08 from a real `simplicio mcp status --json` run against
  // a freshly-built simplicio-runtime binary (SIMPLICIO_BIN) -- a live
  // regression fixture, not a guess at the wire shape.
  it('parses the real observed simplicio mcp status --json payload', () => {
    const real = {
      connections: [
        {
          alive: false,
          client_name: 'claude-code',
          client_version: '1.0.0',
          connected_at: 1783491472,
          last_tool_call_at: 1783491472,
          pid: 29480,
          repo: 'C:\\Users\\Z0059V7A\\m\\ai\\simplicio-runtime',
          tools_used: ['simplicio_map']
        },
        {
          alive: false,
          client_name: 'claude-code',
          client_version: '1.0.0',
          connected_at: 1783491460,
          last_tool_call_at: null,
          pid: 30204,
          repo: 'C:\\Users\\Z0059V7A\\m\\ai\\simplicio-runtime',
          tools_used: []
        }
      ],
      generated_at: 1783491668,
      schema: 'simplicio.mcp-status/v1'
    }

    const parsed = parseMcpStatus(real)

    expect(parsed.generatedAtMs).toBe(1783491668 * 1000)
    expect(parsed.connections).toHaveLength(2)
    expect(parsed.connections[0]).toEqual({
      alive: false,
      clientName: 'claude-code',
      clientVersion: '1.0.0',
      connectedAtMs: 1783491472 * 1000,
      lastToolCallAtMs: 1783491472 * 1000,
      pid: 29480,
      repo: 'C:\\Users\\Z0059V7A\\m\\ai\\simplicio-runtime',
      toolsUsed: ['simplicio_map']
    })
    expect(parsed.connections[1].lastToolCallAtMs).toBeNull()
    expect(parsed.connections[1].toolsUsed).toEqual([])
  })

  it('drops non-object entries inside connections instead of throwing', () => {
    const parsed = parseMcpStatus({ connections: [null, 'nope', 42, { pid: 1, alive: true }] })

    expect(parsed.connections).toHaveLength(1)
    expect(parsed.connections[0].pid).toBe(1)
  })

  it('filters non-string entries out of tools_used', () => {
    const parsed = parseMcpStatus({ connections: [{ tools_used: ['edit', 42, null, '  ', 'read'] }] })

    expect(parsed.connections[0].toolsUsed).toEqual(['edit', 'read'])
  })
})

describe('sortConnectionsForDisplay', () => {
  function conn(overrides: Partial<Parameters<typeof sortConnectionsForDisplay>[0][number]>) {
    return {
      alive: true,
      clientName: 'x',
      clientVersion: null,
      connectedAtMs: null,
      lastToolCallAtMs: null,
      pid: null,
      repo: null,
      toolsUsed: [],
      ...overrides
    }
  }

  it('orders alive connections before dead ones', () => {
    const connections = [conn({ alive: false, clientName: 'Dead' }), conn({ alive: true, clientName: 'Alive' })]
    const sorted = sortConnectionsForDisplay(connections)

    expect(sorted.map(c => c.clientName)).toEqual(['Alive', 'Dead'])
  })

  it('orders alive connections by most-recently-connected first', () => {
    const connections = [
      conn({ clientName: 'Older', connectedAtMs: 1000 }),
      conn({ clientName: 'Newer', connectedAtMs: 5000 })
    ]

    expect(sortConnectionsForDisplay(connections).map(c => c.clientName)).toEqual(['Newer', 'Older'])
  })

  it('falls back to alphabetical clientName when timestamps tie (including both null)', () => {
    const connections = [conn({ clientName: 'Zeta' }), conn({ clientName: 'Alpha' })]

    expect(sortConnectionsForDisplay(connections).map(c => c.clientName)).toEqual(['Alpha', 'Zeta'])
  })

  it('does not mutate the input array', () => {
    const connections = [conn({ clientName: 'B' }), conn({ clientName: 'A' })]
    const original = [...connections]
    sortConnectionsForDisplay(connections)
    expect(connections).toEqual(original)
  })
})

describe('formatConnectionElapsed', () => {
  const now = Date.parse('2026-07-08T12:00:00Z')

  it('returns null for a missing timestamp', () => {
    expect(formatConnectionElapsed(null, now)).toBeNull()
  })

  it('returns null for a future timestamp (clock skew)', () => {
    expect(formatConnectionElapsed(now + 5000, now)).toBeNull()
  })

  it('formats seconds', () => {
    expect(formatConnectionElapsed(now - 30_000, now)).toBe('30s')
  })

  it('formats minutes', () => {
    expect(formatConnectionElapsed(now - 5 * 60_000, now)).toBe('5m')
  })

  it('formats hours and minutes', () => {
    expect(formatConnectionElapsed(now - (2 * 60 + 30) * 60_000, now)).toBe('2h 30m')
  })

  it('formats days and hours', () => {
    expect(formatConnectionElapsed(now - (2 * 24 + 6) * 3_600_000, now)).toBe('2d 6h')
  })
})

describe('matchesEditor / findLiveConnectionForEditor', () => {
  const editor = { id: 'claude-code', name: 'Claude Code' }

  it('matches on a normalized id (case/space/dash insensitive)', () => {
    expect(matchesEditor({ clientName: 'claude-code' }, editor)).toBe(true)
    expect(matchesEditor({ clientName: 'Claude Code' }, editor)).toBe(true)
    expect(matchesEditor({ clientName: 'CLAUDE_CODE' }, editor)).toBe(true)
  })

  it('does not match an unrelated client name', () => {
    expect(matchesEditor({ clientName: 'Cursor' }, editor)).toBe(false)
  })

  it('does not match a null clientName', () => {
    expect(matchesEditor({ clientName: null }, editor)).toBe(false)
  })

  it('findLiveConnectionForEditor only considers alive connections', () => {
    const connections = [
      { alive: false, clientName: 'Claude Code', clientVersion: null, connectedAtMs: null, lastToolCallAtMs: null, pid: null, repo: null, toolsUsed: [] }
    ]

    expect(findLiveConnectionForEditor(connections, editor)).toBeNull()
  })

  it('findLiveConnectionForEditor returns the matching alive connection', () => {
    const connections = [
      { alive: true, clientName: 'Cursor', clientVersion: null, connectedAtMs: null, lastToolCallAtMs: null, pid: null, repo: null, toolsUsed: [] },
      { alive: true, clientName: 'Claude Code', clientVersion: null, connectedAtMs: null, lastToolCallAtMs: null, pid: 9, repo: null, toolsUsed: [] }
    ]

    expect(findLiveConnectionForEditor(connections, editor)?.pid).toBe(9)
  })
})
