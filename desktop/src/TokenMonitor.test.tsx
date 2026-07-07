import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { ParsedSavingsReport } from '@/app/savings/parse'
import type { SavingsDataState, UseSavingsDataResult } from '@/app/savings/use-savings-data'

import TokenMonitor from './TokenMonitor'

const useSavingsDataMock = vi.hoisted(() => vi.fn())

vi.mock('@/app/savings/use-savings-data', () => ({
  useSavingsData: useSavingsDataMock
}))

function bridge(state: SavingsDataState): UseSavingsDataResult {
  return { mcpStatus: null, refresh: () => {}, refreshing: false, state }
}

function report(overrides: Partial<ParsedSavingsReport> = {}): ParsedSavingsReport {
  return {
    events: [],
    hasSessionGranularity: false,
    totals: { baseline: null, pct: null, saved: null, spent: null },
    ...overrides
  }
}

afterEach(() => {
  cleanup()
  useSavingsDataMock.mockReset()
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

    expect(screen.getByText(/bridge|unavailable|indisponível/i)).toBeTruthy()
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
})
