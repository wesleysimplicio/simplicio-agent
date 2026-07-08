// Loading-honesty contract for the cockpit data hook (regression for the
// "Unavailable — Not exposed by this build" flash seen in real Electron
// while slow IPC fetches were in flight):
//  1. in-flight = 'loading', NEVER 'unavailable'/bridgeMissing;
//  2. 'unavailable' only when the method genuinely doesn't exist (sync probe);
//  3. surfaces resolve independently — no slowest-fetch barrier;
//  4. refresh keeps the last good data (stale-while-revalidate).

import { act, cleanup, renderHook, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { initialSurfaceState, mergeSurfaceState, useSavingsData } from './use-savings-data'

interface Deferred<T> {
  promise: Promise<T>
  resolve: (value: T) => void
}

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void
  const promise = new Promise<T>(res => {
    resolve = res
  })

  return { promise, resolve }
}

function installBridge(bridge: Record<string, unknown>): void {
  ;(window as unknown as { simplicioSavings?: unknown }).simplicioSavings = bridge
}

afterEach(() => {
  cleanup()
  delete (window as unknown as { simplicioSavings?: unknown }).simplicioSavings
  vi.restoreAllMocks()
})

describe('initialSurfaceState / mergeSurfaceState (pure)', () => {
  it('starts as loading when the method exists, unavailable when it does not', () => {
    expect(initialSurfaceState(true)).toEqual({ status: 'loading' })
    expect(initialSurfaceState(false)).toEqual({ status: 'unavailable' })
  })

  it('never regresses resolved data to loading/unavailable, but accepts new data and real errors', () => {
    const ok = { data: { x: 1 }, status: 'ok' } as const

    expect(mergeSurfaceState(ok, { status: 'loading' })).toBe(ok)
    expect(mergeSurfaceState(ok, { status: 'unavailable' })).toBe(ok)
    expect(mergeSurfaceState(ok, { data: { x: 2 }, status: 'ok' })).toEqual({ data: { x: 2 }, status: 'ok' })
    expect(mergeSurfaceState(ok, { error: 'boom', status: 'error' })).toEqual({ error: 'boom', status: 'error' })
    expect(mergeSurfaceState({ status: 'loading' }, { status: 'unavailable' })).toEqual({ status: 'unavailable' })
  })
})

describe('useSavingsData loading honesty', () => {
  it('reports loading (not unavailable) for every existing method while fetches are in flight', () => {
    installBridge({
      doctorRun: () => new Promise(() => {}),
      mcpDaemonStatus: () => new Promise(() => {}),
      memoryStatus: () => new Promise(() => {}),
      savingsReport: () => new Promise(() => {}),
      savingsSessions: () => new Promise(() => {})
    })

    const { result } = renderHook(() => useSavingsData())

    expect(result.current.state.status).toBe('loading')
    expect(result.current.mcp.status).toBe('loading')
    expect(result.current.doctor.status).toBe('loading')
    expect(result.current.memory.status).toBe('loading')
    expect(result.current.sessions.status).toBe('loading')
  })

  it('reports unavailable immediately (no fetch) for a method that does not exist', () => {
    const memoryStatus = vi.fn(() => new Promise(() => {}))

    installBridge({
      mcpDaemonStatus: () => new Promise(() => {}),
      memoryStatus,
      savingsReport: () => new Promise(() => {})
      // doctorRun and savingsSessions genuinely absent
    })

    const { result } = renderHook(() => useSavingsData())

    expect(result.current.doctor.status).toBe('unavailable')
    expect(result.current.sessions.status).toBe('unavailable')
    // The existing methods still load normally.
    expect(result.current.memory.status).toBe('loading')
    expect(memoryStatus).toHaveBeenCalled()
  })

  it('resolves surfaces independently — a slow doctor does not hold back memory or mcp', async () => {
    const doctorGate = deferred<{ ok: true; doctor: unknown }>()

    installBridge({
      doctorRun: () => doctorGate.promise,
      mcpDaemonStatus: () => Promise.resolve({ restarts: 0, running: true }),
      memoryStatus: () => Promise.resolve({ memory: { status: 'ready' }, ok: true }),
      savingsReport: () => Promise.resolve({ ok: true, report: { totals: { baseline: 10, spent: 1 } } }),
      savingsSessions: () => Promise.resolve({ ok: true, sessions: [], skipped: 0, sources: [] })
    })

    const { result } = renderHook(() => useSavingsData())

    // Fast surfaces land while doctor is still pending.
    await waitFor(() => {
      expect(result.current.mcp.status).toBe('ok')
      expect(result.current.memory.status).toBe('ok')
      expect(result.current.state.status).toBe('ok')
    })
    expect(result.current.doctor.status).toBe('loading')
    expect(result.current.refreshing).toBe(true)

    await act(async () => {
      doctorGate.resolve({ doctor: { overall_status: 'ok', policy: { model: 'm' } }, ok: true })
      await doctorGate.promise
    })

    await waitFor(() => {
      expect(result.current.doctor.status).toBe('ok')
      expect(result.current.refreshing).toBe(false)
    })
  })

  it('daemon control calls the bridge action and re-fetches the status', async () => {
    let running = false
    const mcpDaemonStart = vi.fn(() => {
      running = true

      return Promise.resolve({ restarts: 0, running })
    })
    const mcpDaemonStatus = vi.fn(() => Promise.resolve({ restarts: 0, running }))

    installBridge({
      mcpDaemonStart,
      mcpDaemonStatus,
      mcpDaemonStop: vi.fn(),
      savingsReport: () => Promise.resolve({ ok: true, report: {} })
    })

    const { result } = renderHook(() => useSavingsData())

    await waitFor(() => expect(result.current.mcp.status).toBe('ok'))
    expect(result.current.mcpControl.canControl).toBe(true)
    expect(result.current.mcp.status === 'ok' && result.current.mcp.data.running).toBe(false)

    const statusCallsBefore = mcpDaemonStatus.mock.calls.length

    await act(async () => {
      result.current.mcpControl.start()
    })

    await waitFor(() => {
      expect(result.current.mcp.status === 'ok' && result.current.mcp.data.running).toBe(true)
      expect(result.current.mcpControl.pending).toBe(false)
    })
    expect(mcpDaemonStart).toHaveBeenCalledTimes(1)
    // The action is followed by an immediate status re-fetch.
    expect(mcpDaemonStatus.mock.calls.length).toBeGreaterThan(statusCallsBefore)
    expect(result.current.mcpControl.error).toBeNull()
  })

  it('daemon control surfaces the real error from a failed action', async () => {
    installBridge({
      mcpDaemonStart: () => Promise.reject(new Error('spawn simplicio ENOENT')),
      mcpDaemonStatus: () => Promise.resolve({ restarts: 0, running: false }),
      mcpDaemonStop: vi.fn(),
      savingsReport: () => Promise.resolve({ ok: true, report: {} })
    })

    const { result } = renderHook(() => useSavingsData())

    await waitFor(() => expect(result.current.mcp.status).toBe('ok'))

    await act(async () => {
      result.current.mcpControl.start()
    })

    await waitFor(() => expect(result.current.mcpControl.error).toBe('spawn simplicio ENOENT'))
  })

  it('keeps the last good data during a refresh (stale-while-revalidate)', async () => {
    let memoryCalls = 0
    const secondGate = deferred<{ ok: true; memory: unknown }>()

    installBridge({
      mcpDaemonStatus: () => Promise.resolve({ restarts: 0, running: true }),
      memoryStatus: () => {
        memoryCalls += 1

        return memoryCalls === 1
          ? Promise.resolve({ memory: { selected_backend: 'sqlite-fts5', status: 'ready' }, ok: true })
          : secondGate.promise
      },
      savingsReport: () => Promise.resolve({ ok: true, report: {} })
    })

    const { result } = renderHook(() => useSavingsData())

    await waitFor(() => expect(result.current.memory.status).toBe('ok'))
    const firstData = result.current.memory

    // Manual refresh: the second memory fetch hangs — the card must keep the
    // resolved data (with the global refreshing flag up), not regress.
    act(() => result.current.refresh())

    expect(result.current.refreshing).toBe(true)
    expect(result.current.memory).toBe(firstData)
    expect(result.current.memory.status).toBe('ok')

    await act(async () => {
      secondGate.resolve({ memory: { selected_backend: 'vector', status: 'ready' }, ok: true })
      await secondGate.promise
    })

    await waitFor(() => {
      expect(result.current.memory.status === 'ok' && result.current.memory.data.backend).toBe('vector')
    })
  })
})
