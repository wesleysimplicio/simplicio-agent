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

/** `simplicio doctor --json` payload — schema owned by the runtime, not stable. */
export type DoctorRunResult = { ok: true; doctor: unknown } | { ok: false; error: string }

/** `simplicio memory status --json` payload — schema `simplicio.memory-backend/v1`. */
export type MemoryStatusResult = { ok: true; memory: unknown } | { ok: false; error: string }

/** Per-run session groups read straight from the savings ledgers (no spawn). */
export interface SavingsSessionsOk {
  ok: true
  sessions: unknown[]
  skipped: number
  sources: string[]
}

export interface SavingsSessionsErr {
  ok: false
  error: string
  sessions?: unknown[]
  skipped?: number
  sources?: string[]
}

export type SavingsSessionsResult = SavingsSessionsErr | SavingsSessionsOk

export interface SimplicioSavingsBridge {
  // `opts.repoPath` scopes the report to the active project's repo root
  // (issue #128) — omit to keep the previous HOME-only behavior.
  savingsReport: (opts?: { repoPath?: string }) => Promise<SavingsReportResult>
  mcpDaemonStatus: () => Promise<McpDaemonStatus>
  // Cockpit extensions — optional because a given preload build may predate
  // them; an absent method degrades to an honest "unavailable" state.
  doctorRun?: () => Promise<DoctorRunResult>
  memoryStatus?: () => Promise<MemoryStatusResult>
  savingsSessions?: (opts?: { repoPath?: string }) => Promise<SavingsSessionsResult>
  // Daemon control — the main process's supervised start/stop; both resolve
  // with the daemon's fresh status.
  mcpDaemonStart?: () => Promise<McpDaemonStatus>
  mcpDaemonStop?: () => Promise<McpDaemonStatus>
}

/**
 * `proof.kind` per `docs/SAVINGS_EVENT_SPEC.md` — the honesty ladder from
 * weakest to strongest evidence: `estimated` (heuristic guess) <
 * `benchmark` (offline reference run, not this session's real usage) <
 * `replayed` (this session's own recorded trace, replayed deterministically)
 * < `measured` (a real, live provider/ledger receipt for this exact run).
 * Never unlabeled — an event with no recognizable kind is `null`, not a guess.
 */
export type ProofKind = 'benchmark' | 'estimated' | 'measured' | 'replayed'

const PROOF_KINDS: readonly ProofKind[] = ['measured', 'replayed', 'benchmark', 'estimated']

export function isProofKind(value: unknown): value is ProofKind {
  return typeof value === 'string' && (PROOF_KINDS as readonly string[]).includes(value)
}

/**
 * Rank used to pick the single "headline" kind when a report mixes several —
 * lower is stronger evidence. `measured` always outranks the rest, so a
 * report that has even one real measured event never headlines a weaker kind.
 */
export function proofKindRank(kind: ProofKind): number {
  return PROOF_KINDS.indexOf(kind)
}
