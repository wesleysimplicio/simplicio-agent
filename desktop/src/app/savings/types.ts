// Local type contract for the `window.simplicioSavings` preload bridge.
//
// This is declared here (not in `src/global.d.ts`) on purpose: another agent
// is wiring the actual preload implementation in parallel, so this file
// programs defensively against the *documented* contract instead of racing
// a shared global-declaration file. Once the bridge lands in
// `global.d.ts`, this can be narrowed to re-export from there — until then,
// every call site treats the bridge as `unknown` at the boundary and never
// trusts its shape past a single optional-chained call.

/** `simplicio savings report --json` — schema `simplicio.savings-event/v1`, aggregated. */
export type SavingsRawReport = unknown

export interface SavingsReportOk {
  ok: true
  report: SavingsRawReport
}

export interface SavingsReportErr {
  ok: false
  error: string
}

export type SavingsReportResult = SavingsReportOk | SavingsReportErr

export interface McpDaemonStatus {
  running: boolean
  pid?: number
  restarts: number
  startedAt?: string
  lastError?: string
}

export interface SimplicioSavingsBridge {
  savingsReport: () => Promise<SavingsReportResult>
  mcpDaemonStatus: () => Promise<McpDaemonStatus>
}

/** `proof.kind` per `docs/SAVINGS_EVENT_SPEC.md` — measured beats estimated, never unlabeled. */
export type ProofKind = 'estimated' | 'measured'

export function isProofKind(value: unknown): value is ProofKind {
  return value === 'measured' || value === 'estimated'
}
