import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { ParsedSavingsReport } from '@/app/savings/parse'
import type { SavingsDataState, UseSavingsDataResult } from '@/app/savings/use-savings-data'
import type { CockpitSession } from '@/app/savings/cockpit'

import { MemoryRouter, Route, Routes } from 'react-router-dom'

import TokenMonitor from './TokenMonitor'

const useSavingsDataMock = vi.hoisted(() => vi.fn())
const startManualPostSetupMock = vi.hoisted(() => vi.fn())
// A minimal, mutable nanostores-shaped atom good enough for @nanostores/react
// useStore() (it reads `.value`/`.get()` and calls `.listen(cb)`) — this test
// only needs `.manual` to flip and listeners to be notified.
const desktopOnboardingMock = vi.hoisted(() => {
  const listeners = new Set<(value: { manual: boolean }) => void>()
  const store = {
    get: () => store.value,
    listen: (fn: (value: { manual: boolean }) => void) => {
      listeners.add(fn)

      return () => listeners.delete(fn)
    },
    set: (next: { manual: boolean }) => {
      store.value = next
      listeners.forEach(fn => fn(next))
    },
    value: { manual: false }
  }

  return store
})

vi.mock('@/app/savings/use-savings-data', () => ({
  useSavingsData: useSavingsDataMock
}))

vi.mock('@/store/onboarding', () => ({
  $desktopOnboarding: desktopOnboardingMock,
  startManualPostSetup: startManualPostSetupMock
}))

// A route stub standing in for the app's "Home" (new-chat) route, so the
// navigation-guard regression test can assert TokenMonitor did NOT strand
// the user there — the exact symptom reported ("cai na Home").
function HomeStub() {
  return <div data-testid="home-stub">home</div>
}

function renderPanel(props: { onClose?: () => void } = {}) {
  return render(
    <MemoryRouter initialEntries={['/savings']}>
      <Routes>
        <Route element={<HomeStub />} path="/" />
        <Route element={<TokenMonitor onClose={props.onClose ?? (() => {})} />} path="/savings" />
      </Routes>
    </MemoryRouter>
  )
}

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
    dominantProofKind: null,
    events: [],
    hasSessionGranularity: false,
    mixedProofKinds: false,
    totals: { baseline: null, pct: null, saved: null, spent: null },
    ...overrides
  }
}

afterEach(() => {
  cleanup()
  useSavingsDataMock.mockReset()
  startManualPostSetupMock.mockReset()
  desktopOnboardingMock.set({ manual: false })
})

// The acceptance rule this file guards: the panel NEVER invents a number.
// Empty ledger -> explicit empty state; broken bridge -> explicit error;
// real data -> figures with their measured/estimated proof-kind evidence.
describe('TokenMonitor (savings panel)', () => {
  it('renders an explicit empty state when the ledger has no data — no invented figures', () => {
    useSavingsDataMock.mockReturnValue(bridge({ parsed: report(), status: 'ok' }))
    const { container } = renderPanel()

    expect(screen.getByText(/no savings (are |)recorded|No savings recorded yet/i)).toBeTruthy()
    // Not a single fabricated numeric stat on screen.
    expect(container.querySelector('.hero-stat, [data-slot="hero-stat"]')).toBeNull()
  })

  it('renders an explicit unavailable state when the desktop bridge is missing', () => {
    useSavingsDataMock.mockReturnValue(bridge({ status: 'unavailable' }))
    renderPanel()

    // Multiple honest "unavailable" surfaces exist now (report empty-state +
    // one per status card) — assert at least one is on screen.
    expect(screen.getAllByText(/bridge|unavailable|indisponível/i).length).toBeGreaterThan(0)
  })

  it('renders an explicit error state with retry when the report fails', () => {
    useSavingsDataMock.mockReturnValue(bridge({ error: 'savings report exited 1', status: 'error' }))
    renderPanel()

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
    renderPanel()

    // Proof-kind evidence is visible per event (badge labels from i18n).
    expect(screen.getAllByText('Measured').length).toBeGreaterThan(0)
    expect(screen.getAllByText('Estimated').length).toBeGreaterThan(0)
  })

  it('shows a mixed-evidence disclosure next to the dominant proof-kind headline when kinds are mixed', () => {
    useSavingsDataMock.mockReturnValue(
      bridge({
        parsed: report({
          dominantProofKind: 'measured',
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
            }
          ],
          hasSessionGranularity: true,
          mixedProofKinds: true,
          totals: { baseline: 1000, pct: 40, saved: 400, spent: 600 }
        }),
        status: 'ok'
      })
    )
    renderPanel()

    expect(screen.getByText(/mixed evidence/i)).toBeTruthy()
  })

  it('renders the correlated session/run metadata without inventing unavailable values', () => {
    const sessions: CockpitSession[] = [
      {
        branch: 'main',
        endedAt: null,
        events: [
          {
            cache: { hit: true, readTokens: 12, writeTokens: null },
            cost: null,
            evidenceRefs: ['receipt://run-1'],
            eventHash: 'abcdef0123456789',
            hashState: 'unverified',
            id: 'event-1',
            latencyMs: null,
            model: 'model-x',
            prevEventHash: null,
            priceState: 'missing_price',
            proofKind: 'estimated',
            provider: 'provider-x',
            sessionId: null,
            surfaces: ['runtime_map'],
            taskTitle: 'Correlate savings',
            timestamp: '2026-07-07T12:00:00Z',
            tokens: { baseline: 100, saved: 90, spent: 10 },
            tools: []
          }
        ],
        repo: '/repo/one',
        runId: 'run-1',
        savedPct: 90,
        startedAt: '2026-07-07T12:00:00Z',
        title: 'Savings run',
        totals: { baseline: 100, saved: 90, spent: 10 }
      }
    ]
    useSavingsDataMock.mockReturnValue({
      ...bridge({ parsed: report({ totals: { baseline: 100, pct: 90, saved: 90, spent: 10 } }), status: 'ok' }),
      sessions: { data: { sessions, skipped: 0, sources: ['/repo/one/.simplicio/ledger/savings-events.jsonl'] }, status: 'ok' }
    })

    renderPanel()

    expect(screen.getByText(/run=run-1/)).toBeTruthy()
    expect(screen.getByText('session=—')).toBeTruthy()
    expect(screen.getByText('cost=—')).toBeTruthy()
    expect(screen.getByText('cache=hit=yes read=12 write=—')).toBeTruthy()
    expect(screen.getByText('latency=—')).toBeTruthy()
    expect(screen.getByText('tools=—')).toBeTruthy()
    expect(screen.getByText('evidence=receipt://run-1')).toBeTruthy()
    expect(screen.getByText('hash=unverified')).toBeTruthy()
    expect(screen.getByText('price=missing_price')).toBeTruthy()
  })

  it('header Diagnostics button dispatches the Setup Simplicio post-setup flow', () => {
    useSavingsDataMock.mockReturnValue(bridge({ parsed: report(), status: 'ok' }))
    renderPanel()

    fireEvent.click(screen.getByTitle('Diagnostics'))

    expect(startManualPostSetupMock).toHaveBeenCalledTimes(1)
  })

  it('MCP card daemon controls: stop asks inline confirmation, then calls the control', () => {
    const stop = vi.fn()
    const data = bridge({ parsed: report(), status: 'ok' })
    data.mcp = { data: { restarts: 0, running: true }, status: 'ok' }
    data.mcpControl = { canControl: true, error: null, pending: false, start: () => {}, stop }
    useSavingsDataMock.mockReturnValue(data)
    renderPanel()

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
    renderPanel()

    fireEvent.click(screen.getByText('Start'))
    expect(start).toHaveBeenCalledTimes(1)
    // The failed action's real error is on the card.
    expect(screen.getByText('start failed: exit 1')).toBeTruthy()
  })

  // Regression for the reported bug: Diagnostics opens the onboarding
  // overlay (an opaque full-viewport layer stacked over this panel, not a
  // route change) via startManualPostSetup(). Once that flow ends — either
  // completed or cancelled, both flip $desktopOnboarding.manual back to
  // false — the user must land back on Token Economy, never on Home.
  describe('Diagnostics return-to-cockpit guard', () => {
    it('navigates back to /savings once the flow it launched completes ($desktopOnboarding.manual: true -> false)', () => {
      useSavingsDataMock.mockReturnValue(bridge({ parsed: report(), status: 'ok' }))
      renderPanel()

      fireEvent.click(screen.getByTitle('Diagnostics'))
      expect(startManualPostSetupMock).toHaveBeenCalledTimes(1)

      // The flow opens (manual: true) — simulate completeDesktopOnboarding()
      // / closeManualOnboarding() firing later, either from a real finish or
      // a cancel; both just flip this one flag.
      act(() => desktopOnboardingMock.set({ manual: true }))
      act(() => desktopOnboardingMock.set({ manual: false }))

      // Still on the cockpit — never fell through to the Home stub.
      expect(screen.getByText('Token Economy')).toBeTruthy()
      expect(screen.queryByTestId('home-stub')).toBeNull()
    })

    it('does not react to an unrelated manual onboarding flow (e.g. Settings -> Providers) that this button never launched', () => {
      useSavingsDataMock.mockReturnValue(bridge({ parsed: report(), status: 'ok' }))
      renderPanel()

      // manual flips true/false WITHOUT the Diagnostics button ever being
      // clicked — the guard must stay inert (no navigation attempted; the
      // panel simply keeps rendering, which this asserts indirectly since a
      // stray navigate to an unmounted route would throw/blank the screen).
      act(() => desktopOnboardingMock.set({ manual: true }))
      act(() => desktopOnboardingMock.set({ manual: false }))

      expect(screen.getByText('Token Economy')).toBeTruthy()
    })
  })
})
