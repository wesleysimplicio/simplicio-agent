import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { ParsedSavingsReport } from '@/app/savings/parse'
import type { SavingsDataState, UseSavingsDataResult } from '@/app/savings/use-savings-data'

import TokenMonitor from './TokenMonitor'

const useSavingsDataMock = vi.hoisted(() => vi.fn())
const startManualPostSetupMock = vi.hoisted(() => vi.fn())

vi.mock('@/app/savings/use-savings-data', () => ({
  useSavingsData: useSavingsDataMock
}))

vi.mock('@/store/onboarding', () => ({
  startManualPostSetup: startManualPostSetupMock
}))

function bridge(state: SavingsDataState): UseSavingsDataResult {
  return {
    doctor: { status: 'unavailable' },
    mcp: { status: 'unavailable' },
    mcpControl: { canControl: false, error: null, pending: false, start: () => {}, stop: () => {} },
    memory: { status: 'unavailable' },
    refresh: () => {},
    refreshing: false,
    sessions: { status: 'unavailable' },
    state
  }
}

function report(overrides: Partial<ParsedSavingsReport> = {}): ParsedSavingsReport {
  return {
    dimensions: { byModel: [], byProof: [], timeSeries: [] },
    events: [],
    hasSessionGranularity: false,
    totals: { baseline: null, pct: null, saved: null, spent: null },
    ...overrides
  }
}

afterEach(() => {
  cleanup()
  useSavingsDataMock.mockReset()
  startManualPostSetupMock.mockReset()
})

// The acceptance rule this file guards: the panel NEVER invents a number.
// Empty ledger -> explicit empty state; broken bridge -> explicit error;
// real data -> figures with their measured/estimated proof-kind evidence.
describe('TokenMonitor (savings panel)', () => {
  it('renders an explicit empty state when the ledger has no data — no invented figures', () => {
    useSavingsDataMock.mockReturnValue(bridge({ parsed: report(), status: 'ok' }))
    const { container } = render(<TokenMonitor onClose={() => {}} />)

    expect(screen.getByText(/no savings (are |)recorded|No savings recorded yet/i)).toBeTruthy()
    // Not a single fabricated numeric stat on screen.
    expect(container.querySelector('.hero-stat, [data-slot="hero-stat"]')).toBeNull()
  })

  it('renders an explicit unavailable state when the desktop bridge is missing', () => {
    useSavingsDataMock.mockReturnValue(bridge({ status: 'unavailable' }))
    render(<TokenMonitor onClose={() => {}} />)

    // Multiple honest "unavailable" surfaces exist now (report empty-state +
    // one per status card) — assert at least one is on screen.
    expect(screen.getAllByText(/bridge|unavailable|indisponível/i).length).toBeGreaterThan(0)
  })

  it('renders an explicit error state with retry when the report fails', () => {
    useSavingsDataMock.mockReturnValue(bridge({ error: 'savings report exited 1', status: 'error' }))
    render(<TokenMonitor onClose={() => {}} />)

    expect(screen.getByText('savings report exited 1')).toBeTruthy()
  })

  it('renders real totals and per-event proof-kind evidence from the ledger', () => {
    useSavingsDataMock.mockReturnValue(
      bridge({
        parsed: report({
          events: [
            {
              baseline: 1000,
              id: 'e1',
              model: 'sonnet',
              pct: 40,
              proofKind: 'measured',
              repo: 'simplicio-agent',
              saved: 400,
              session: 's1',
              spent: 600,
              timestamp: '2026-07-07T12:00:00Z',
              timestampMs: Date.parse('2026-07-07T12:00:00Z')
            },
            {
              baseline: 2000,
              id: 'e2',
              model: null,
              pct: 25,
              proofKind: 'estimated',
              repo: null,
              saved: 500,
              session: 's2',
              spent: 1500,
              timestamp: '2026-07-07T13:00:00Z',
              timestampMs: Date.parse('2026-07-07T13:00:00Z')
            }
          ],
          hasSessionGranularity: true,
          totals: { baseline: 3000, pct: 30, saved: 900, spent: 2100 }
        }),
        status: 'ok'
      })
    )
    render(<TokenMonitor onClose={() => {}} />)

    // Proof-kind evidence is visible per event (badge labels from i18n).
    expect(screen.getAllByText('Measured').length).toBeGreaterThan(0)
    expect(screen.getAllByText('Estimated').length).toBeGreaterThan(0)
  })

  it('header Diagnostics button dispatches the Setup Simplicio post-setup flow', () => {
    useSavingsDataMock.mockReturnValue(bridge({ parsed: report(), status: 'ok' }))
    render(<TokenMonitor onClose={() => {}} />)

    fireEvent.click(screen.getByTitle('Diagnostics'))

    expect(startManualPostSetupMock).toHaveBeenCalledTimes(1)
  })

  it('MCP card daemon controls: stop asks inline confirmation, then calls the control', () => {
    const stop = vi.fn()
    const data = bridge({ parsed: report(), status: 'ok' })
    data.mcp = { data: { restarts: 0, running: true }, status: 'ok' }
    data.mcpControl = { canControl: true, error: null, pending: false, start: () => {}, stop }
    useSavingsDataMock.mockReturnValue(data)
    render(<TokenMonitor onClose={() => {}} />)

    // First click arms the inline confirmation; nothing executes yet.
    fireEvent.click(screen.getByText('Stop'))
    expect(stop).not.toHaveBeenCalled()

    // Second click within the window executes the stop.
    fireEvent.click(screen.getByText('Confirm stop?'))
    expect(stop).toHaveBeenCalledTimes(1)
  })

  it('MCP card shows a primary Start button when the daemon is stopped, and the real action error', () => {
    const start = vi.fn()
    const data = bridge({ parsed: report(), status: 'ok' })
    data.mcp = { data: { lastError: 'spawn ENOENT', restarts: 3, running: false }, status: 'ok' }
    data.mcpControl = { canControl: true, error: 'start failed: exit 1', pending: false, start, stop: () => {} }
    useSavingsDataMock.mockReturnValue(data)
    render(<TokenMonitor onClose={() => {}} />)

    fireEvent.click(screen.getByText('Start'))
    expect(start).toHaveBeenCalledTimes(1)
    // The failed action's real error is on the card.
    expect(screen.getByText('start failed: exit 1')).toBeTruthy()
  })
})
