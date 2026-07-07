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

export async function fetchSavingsReport(): Promise<SavingsReportOutcome> {
  const bridge = getBridge()

  if (!bridge) {
    return { kind: 'unavailable' }
  }

  try {
    const result = await bridge.savingsReport()

    if (result?.ok) {
      return { kind: 'ok', report: result.report }
    }

    return { error: result?.error || 'Unknown error from savings report bridge', kind: 'error' }
  } catch (err) {
    return { error: err instanceof Error ? err.message : String(err), kind: 'error' }
  }
}

export async function fetchMcpDaemonStatus(): Promise<McpDaemonStatus | null> {
  const bridge = getBridge()

  if (!bridge) {
    return null
  }

  try {
    return await bridge.mcpDaemonStatus()
  } catch {
    return null
  }
}
