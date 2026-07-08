// Thin, defensive wrapper around `window.simplicioSavings.dashboardStatus` /
// `dashboardSummary` / `dashboardStart` / `dashboardStop` — the native web
// dashboard (`simplicio dashboard`) aggregation surface that feeds "Live
// Activity". Declared locally (not from `global.d.ts`) on purpose: a parallel
// in-flight change owns the actual preload wiring for these four methods, so
// this file never assumes they exist. Every call goes through a synchronous
// `typeof` capability probe first — a method that genuinely isn't exposed by
// this build degrades to an honest 'unavailable' outcome, never a crash or a
// fake number. Same shape/contract as `bridge.ts`'s savings-report wrapper.

export interface DashboardStatus {
  running: boolean
  port: null | number
  pid: null | number
  startedAt: null | string
  lastError: null | string
}

export interface DashboardSummaryOpts {
  repoPath?: string
  /** Timeseries bucket granularity, e.g. 'hour' for the live heartbeat chart. */
  group?: string
}

/** `simplicio dashboard`'s aggregation payload — schema owned by the runtime,
 * not stable here. Parsed defensively by `dashboard-parse.ts`. */
export type DashboardRawSummary = unknown

export type DashboardSummaryResult = { ok: true; summary: DashboardRawSummary } | { ok: false; error: string }

interface DashboardBridgeMethods {
  dashboardStatus: () => Promise<DashboardStatus>
  dashboardSummary: (opts?: DashboardSummaryOpts) => Promise<DashboardSummaryResult>
  dashboardStart: () => Promise<DashboardStatus>
  dashboardStop: () => Promise<DashboardStatus>
}

function getSavingsWindow(): Partial<DashboardBridgeMethods> | undefined {
  if (typeof window === 'undefined') {
    return undefined
  }

  const candidate = (window as unknown as { simplicioSavings?: unknown }).simplicioSavings

  return candidate && typeof candidate === 'object' ? (candidate as Partial<DashboardBridgeMethods>) : undefined
}

/** Synchronous capability probe — no IPC round trip, so a method that exists
 * starts its surface as 'loading', never as "bridge missing". Each method is
 * checked independently: an older preload build may expose dashboardStatus
 * without dashboardStart/dashboardStop, and this hook must degrade honestly
 * per-capability rather than all-or-nothing. */
export interface DashboardCapabilities {
  dashboardStatus: boolean
  dashboardSummary: boolean
  dashboardControl: boolean
}

export function getDashboardCapabilities(): DashboardCapabilities {
  const w = getSavingsWindow()

  return {
    dashboardControl: typeof w?.dashboardStart === 'function' && typeof w?.dashboardStop === 'function',
    dashboardStatus: typeof w?.dashboardStatus === 'function',
    dashboardSummary: typeof w?.dashboardSummary === 'function'
  }
}

export type DashboardOutcome<T> = { kind: 'error'; error: string } | { kind: 'ok'; payload: T } | { kind: 'unavailable' }

function normalizeStatus(raw: unknown): DashboardStatus {
  const r = (raw ?? {}) as Partial<DashboardStatus>

  return {
    lastError: typeof r.lastError === 'string' ? r.lastError : null,
    pid: typeof r.pid === 'number' ? r.pid : null,
    port: typeof r.port === 'number' ? r.port : null,
    running: r.running === true,
    startedAt: typeof r.startedAt === 'string' ? r.startedAt : null
  }
}

export async function fetchDashboardStatus(): Promise<DashboardOutcome<DashboardStatus>> {
  const w = getSavingsWindow()

  if (typeof w?.dashboardStatus !== 'function') {
    return { kind: 'unavailable' }
  }

  try {
    return { kind: 'ok', payload: normalizeStatus(await w.dashboardStatus()) }
  } catch (err) {
    return { error: err instanceof Error ? err.message : String(err), kind: 'error' }
  }
}

export async function fetchDashboardSummary(opts?: DashboardSummaryOpts): Promise<DashboardOutcome<DashboardRawSummary>> {
  const w = getSavingsWindow()

  if (typeof w?.dashboardSummary !== 'function') {
    return { kind: 'unavailable' }
  }

  try {
    const result = await w.dashboardSummary(opts)

    if (result?.ok) {
      return { kind: 'ok', payload: result.summary }
    }

    return { error: result?.error || 'Unknown error from dashboard summary bridge', kind: 'error' }
  } catch (err) {
    return { error: err instanceof Error ? err.message : String(err), kind: 'error' }
  }
}

/** Supervised dashboard daemon start/stop; both resolve with the daemon's
 * fresh status. Used to auto-start the dashboard once when Live Activity
 * mounts and finds it not running, and by the manual "Try again" retry. */
export async function controlDashboard(action: 'start' | 'stop'): Promise<DashboardOutcome<DashboardStatus>> {
  const w = getSavingsWindow()
  const method = action === 'start' ? w?.dashboardStart : w?.dashboardStop

  if (typeof method !== 'function') {
    return { kind: 'unavailable' }
  }

  try {
    return { kind: 'ok', payload: normalizeStatus(await method()) }
  } catch (err) {
    return { error: err instanceof Error ? err.message : String(err), kind: 'error' }
  }
}
