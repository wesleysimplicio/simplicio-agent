import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import type { McpConnectionsState } from './use-mcp-connections'
import { McpConnectionsSection } from './mcp-connections-section'

afterEach(() => {
  cleanup()
})

// Default `useI18n()` context (no provider) resolves to the English catalog,
// so these assertions read the real `en.ts` copy — same convention as
// `scroll-to-bottom-button.test.tsx`.

describe('McpConnectionsSection', () => {
  it('renders the honest empty state when the backend is ok but nothing is connected', () => {
    const state: McpConnectionsState = { connections: [], generatedAtMs: null, status: 'ok', updatedAtMs: Date.now() }
    render(<McpConnectionsSection state={state} />)

    expect(screen.getByText('No MCP client connected right now')).toBeTruthy()
    // Never renders a fabricated "Connected" badge when there's nothing there.
    expect(screen.queryByText('Connected')).toBeNull()
  })

  it('renders the honest unavailable state with the real backend error, never masked', () => {
    const state: McpConnectionsState = {
      error: "simplicio: unknown mcp subcommand 'status' (use add|list|remove|catalog|search|install|auth|token|logout)",
      status: 'unavailable'
    }
    render(<McpConnectionsSection state={state} />)

    expect(screen.getByText('Live status unavailable')).toBeTruthy()
    expect(screen.getByText(/unknown mcp subcommand 'status'/)).toBeTruthy()
  })

  it('renders a loading skeleton (no data claims) while the first poll is in flight', () => {
    render(<McpConnectionsSection state={{ status: 'loading' }} />)

    expect(screen.queryByText('No MCP client connected right now')).toBeNull()
    expect(screen.queryByText('Live status unavailable')).toBeNull()
  })

  it('renders alive connections with a Connected badge, pid, and tool chips', () => {
    const state: McpConnectionsState = {
      connections: [
        {
          alive: true,
          clientName: 'Claude Code',
          clientVersion: '2.1.0',
          connectedAtMs: Date.now() - 5 * 60_000,
          lastToolCallAtMs: Date.now() - 60_000,
          pid: 4242,
          repo: 'wesleysimplicio/simplicio-agent',
          toolsUsed: ['edit', 'read']
        }
      ],
      generatedAtMs: Date.now(),
      status: 'ok',
      updatedAtMs: Date.now()
    }
    render(<McpConnectionsSection state={state} />)

    expect(screen.getByText('Claude Code')).toBeTruthy()
    expect(screen.getByText('Connected')).toBeTruthy()
    expect(screen.getByText('PID 4242')).toBeTruthy()
    expect(screen.getByText('v2.1.0')).toBeTruthy()
    expect(screen.getByText('edit')).toBeTruthy()
    expect(screen.getByText('read')).toBeTruthy()
  })

  it('renders a dead connection with the Disconnected label instead of Connected', () => {
    const state: McpConnectionsState = {
      connections: [
        {
          alive: false,
          clientName: 'Cursor',
          clientVersion: null,
          connectedAtMs: Date.now() - 3_600_000,
          lastToolCallAtMs: Date.now() - 1_800_000,
          pid: null,
          repo: null,
          toolsUsed: []
        }
      ],
      generatedAtMs: Date.now(),
      status: 'ok',
      updatedAtMs: Date.now()
    }
    render(<McpConnectionsSection state={state} />)

    expect(screen.getByText('Cursor')).toBeTruthy()
    expect(screen.getByText('Disconnected')).toBeTruthy()
    expect(screen.queryByText('Connected')).toBeNull()
  })
})
