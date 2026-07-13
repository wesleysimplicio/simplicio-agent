// Thin, defensive wrapper around `window.simplicioSavings`. The preload
// bridge is owned by a different in-flight change, so this file never
// imports it from `global.d.ts` — it reads `window` as `unknown` and
// type-guards every step, so a not-yet-shipped or reshaped bridge degrades to
// an honest "unavailable" result instead of a crash or a fake number.

import type { McpDaemonStatus, SavingsRawReport, SimplicioSavingsBridge } from './types'

export type SavingsReportOutcome =
  | { kind: 'error'; error: string }
  | { kind: 'ok'; report: SavingsRawReport }
  | { kind: 'unavailable' }

function getBridge(): SimplicioSavingsBridge | undefined {
  if (typeof window === 'undefined') {
    return undefined
  }

  const candidate = (window as unknown as { simplicioSavings?: unknown }).simplicioSavings

  if (
    candidate &&
    typeof candidate === 'object' &&
    typeof (candidate as Partial<SimplicioSavingsBridge>).savingsReport === 'function' &&
    typeof (candidate as Partial<SimplicioSavingsBridge>).mcpDaemonStatus === 'function'
  ) {
    return candidate as SimplicioSavingsBridge
  }

  return undefined
}

export function isSavingsBridgeAvailable(): boolean {
  return getBridge() !== undefined
}

/**
 * Synchronous capability probe — which bridge methods actually exist right
 * now. This is what separates an honest "unavailable" (method truly not
 * exposed by this build) from an in-flight fetch (method exists, IPC still
 * resolving): the probe is a `typeof` check with no IPC round trip, so a
 * surface whose method exists starts as 'loading', never as "bridge missing".
 */
export interface BridgeCapabilities {
  bridge: boolean
  doctorRun: boolean
  mcpDaemonControl: boolean
  mcpDaemonStatus: boolean
  memoryStatus: boolean
  savingsReport: boolean
  savingsSessions: boolean
}

export function getBridgeCapabilities(): BridgeCapabilities {
  const bridge = getBridge()

  return {
    bridge: bridge !== undefined,
    doctorRun: typeof bridge?.doctorRun === 'function',
    mcpDaemonControl: typeof bridge?.mcpDaemonStart === 'function' && typeof bridge?.mcpDaemonStop === 'function',
    mcpDaemonStatus: typeof bridge?.mcpDaemonStatus === 'function',
    memoryStatus: typeof bridge?.memoryStatus === 'function',
    savingsReport: typeof bridge?.savingsReport === 'function',
    savingsSessions: typeof bridge?.savingsSessions === 'function'
  }
}

export async function fetchSavingsReport(repoPath?: string): Promise<SavingsReportOutcome> {
  const bridge = getBridge()

  if (!bridge) {
    return { kind: 'unavailable' }
  }

  try {
    const result = await bridge.savingsReport(repoPath ? { repoPath } : undefined)

    if (result?.ok) {
      return { kind: 'ok', report: result.report }
    }

    return { error: result?.error || 'Unknown error from savings report bridge', kind: 'error' }
  } catch (err) {
    return { error: err instanceof Error ? err.message : String(err), kind: 'error' }
  }
}

/** Shared outcome shape for the cockpit's bridge methods. */
export type CockpitOutcome<T> = { kind: 'error'; error: string } | { kind: 'ok'; payload: T } | { kind: 'unavailable' }

export async function fetchMcpDaemonStatus(): Promise<CockpitOutcome<McpDaemonStatus>> {
  const bridge = getBridge()

  if (!bridge) {
    return { kind: 'unavailable' }
  }

  try {
    return { kind: 'ok', payload: await bridge.mcpDaemonStatus() }
  } catch (err) {
    return { error: err instanceof Error ? err.message : String(err), kind: 'error' }
  }
}

/** Supervised daemon start/stop; both resolve with the daemon's fresh status. */
export async function controlMcpDaemon(action: 'start' | 'stop'): Promise<CockpitOutcome<McpDaemonStatus>> {
  const bridge = getBridge()
  const method = action === 'start' ? bridge?.mcpDaemonStart : bridge?.mcpDaemonStop

  if (!bridge || typeof method !== 'function') {
    return { kind: 'unavailable' }
  }

  try {
    return { kind: 'ok', payload: await method.call(bridge) }
  } catch (err) {
    return { error: err instanceof Error ? err.message : String(err), kind: 'error' }
  }
}

export async function fetchDoctorRun(): Promise<CockpitOutcome<unknown>> {
  const bridge = getBridge()

  if (!bridge || typeof bridge.doctorRun !== 'function') {
    return { kind: 'unavailable' }
  }

  try {
    const result = await bridge.doctorRun()

    if (result?.ok) {
      return { kind: 'ok', payload: result.doctor }
    }

    return { error: result?.error || 'Unknown error from doctor bridge', kind: 'error' }
  } catch (err) {
    return { error: err instanceof Error ? err.message : String(err), kind: 'error' }
  }
}

export async function fetchMemoryStatus(): Promise<CockpitOutcome<unknown>> {
  const bridge = getBridge()

  if (!bridge || typeof bridge.memoryStatus !== 'function') {
    return { kind: 'unavailable' }
  }

  try {
    const result = await bridge.memoryStatus()

    if (result?.ok) {
      return { kind: 'ok', payload: result.memory }
    }

    return { error: result?.error || 'Unknown error from memory status bridge', kind: 'error' }
  } catch (err) {
    return { error: err instanceof Error ? err.message : String(err), kind: 'error' }
  }
}

export interface SessionsPayload {
  sessions: unknown[]
  skipped: number
  sources: string[]
}

export async function fetchSavingsSessions(repoPath?: string): Promise<CockpitOutcome<SessionsPayload>> {
  const bridge = getBridge()

  if (!bridge || typeof bridge.savingsSessions !== 'function') {
    return { kind: 'unavailable' }
  }

  try {
    const result = await bridge.savingsSessions(repoPath ? { repoPath } : undefined)

    if (result?.ok) {
      return {
        kind: 'ok',
        payload: {
          sessions: Array.isArray(result.sessions) ? result.sessions : [],
          skipped: typeof result.skipped === 'number' ? result.skipped : 0,
          sources: Array.isArray(result.sources) ? result.sources : []
        }
      }
    }

    return { error: result?.error || 'Unknown error from savings sessions bridge', kind: 'error' }
  } catch (err) {
    return { error: err instanceof Error ? err.message : String(err), kind: 'error' }
  }
}
