// Pure, defensive parsing for the cockpit's runtime-status surfaces:
// `simplicio memory status --json`, `simplicio doctor --json`, and the
// ledger-backed per-run sessions. Same honesty contract as parse.ts — a
// missing/malformed field is `null`, never a guess. No React/DOM here so
// everything unit-tests with plain objects.

import { isProofKind, type ProofKind } from './types'

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function numOrNull(value: unknown): null | number {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function strOrNull(value: unknown): null | string {
  return typeof value === 'string' && value.trim() !== '' ? value : null
}

function boolOrNull(value: unknown): boolean | null {
  return typeof value === 'boolean' ? value : null
}

// ---------------------------------------------------------------------------
// Memory / neural DB + guardians
// ---------------------------------------------------------------------------

export type GuardianStatus = 'active' | 'armed' | 'idle'

/** Visual tone for a guardian chip dot. Unknown statuses render muted. */
export type GuardianTone = 'good' | 'info' | 'muted' | 'warn'

export interface GuardianInfo {
  name: string
  status: GuardianStatus | null
  role: null | string
  decisions: number
}

export interface MemoryInfo {
  status: null | string
  backend: null | string
  databasePath: null | string
  memoryItems: null | number
  backendOrder: string[]
  guardians: GuardianInfo[]
}

const GUARDIAN_STATUSES: readonly GuardianStatus[] = ['active', 'armed', 'idle']

function guardianStatusOrNull(value: unknown): GuardianStatus | null {
  return typeof value === 'string' && (GUARDIAN_STATUSES as readonly string[]).includes(value)
    ? (value as GuardianStatus)
    : null
}

/** active = green (working now), idle = calm blue/gray, armed = amber (ready to fire). */
export function guardianTone(status: GuardianStatus | null): GuardianTone {
  if (status === 'active') {
    return 'good'
  }

  if (status === 'armed') {
    return 'warn'
  }

  if (status === 'idle') {
    return 'info'
  }

  return 'muted'
}

export function parseMemoryStatus(raw: unknown): MemoryInfo {
  if (!isRecord(raw)) {
    return { backend: null, backendOrder: [], databasePath: null, guardians: [], memoryItems: null, status: null }
  }

  const operator = isRecord(raw.operator_visibility) ? raw.operator_visibility : {}
  const operatorMemory = isRecord(operator.memory) ? operator.memory : {}
  const guardianPolicy = isRecord(raw.guardian_policy) ? raw.guardian_policy : {}
  const rawGuardians = Array.isArray(guardianPolicy.guardians) ? guardianPolicy.guardians : []

  const guardians: GuardianInfo[] = []

  for (const entry of rawGuardians) {
    if (!isRecord(entry)) {
      continue
    }

    const name = strOrNull(entry.name)

    if (!name) {
      continue
    }

    guardians.push({
      decisions: Array.isArray(entry.decisions) ? entry.decisions.length : 0,
      name,
      role: strOrNull(entry.role),
      status: guardianStatusOrNull(entry.status)
    })
  }

  return {
    backend: strOrNull(raw.selected_backend),
    backendOrder: Array.isArray(raw.backend_order) ? raw.backend_order.filter((v): v is string => typeof v === 'string') : [],
    databasePath: strOrNull(raw.database),
    guardians,
    memoryItems: numOrNull(operatorMemory.memory_items),
    status: strOrNull(raw.status)
  }
}

// ---------------------------------------------------------------------------
// Doctor (runtime + local LLM)
// ---------------------------------------------------------------------------

export interface DoctorInfo {
  version: null | string
  overallStatus: null | string
  binary: null | string
  model: null | string
  local: boolean | null
  offlineFirst: boolean | null
}

export function parseDoctor(raw: unknown): DoctorInfo {
  if (!isRecord(raw)) {
    return { binary: null, local: null, model: null, offlineFirst: null, overallStatus: null, version: null }
  }

  const execution = isRecord(raw.execution) ? raw.execution : {}
  const policy = isRecord(raw.policy) ? raw.policy : {}

  return {
    binary: strOrNull(execution.binary),
    local: boolOrNull(policy.local),
    model: strOrNull(policy.model),
    offlineFirst: boolOrNull(policy.offline_first),
    overallStatus: strOrNull(raw.overall_status),
    version: strOrNull(raw.version)
  }
}

/** The LLM card is healthy when the doctor ran ok/warning AND a model is set. */
export function llmHealthy(doctor: DoctorInfo): boolean {
  return (doctor.overallStatus === 'ok' || doctor.overallStatus === 'warning') && doctor.model !== null
}

// ---------------------------------------------------------------------------
// Sessions (ledger drill-down)
// ---------------------------------------------------------------------------

export interface SessionTokens {
  spent: null | number
  baseline: null | number
  saved: null | number
}

export interface CockpitEvent {
  id: string
  timestamp: null | string
  /** Runtime commands used at this step (runtime_map / memory / edit / ...). */
  surfaces: string[]
  taskTitle: null | string
  tokens: SessionTokens
  proofKind: null | ProofKind
  eventHash: null | string
  prevEventHash: null | string
  model: null | string
  provider: null | string
}

export interface CockpitSession {
  runId: string
  title: null | string
  repo: null | string
  branch: null | string
  startedAt: null | string
  endedAt: null | string
  totals: SessionTokens
  /** saved/baseline percentage when both figures are real; never invented. */
  savedPct: null | number
  events: CockpitEvent[]
}

/**
 * Token triple from either the normalized main-process shape
 * ({spent,baseline,saved}) or the raw ledger field names
 * ({actual_total,baseline_total,saved_total}).
 */
function parseTokens(raw: unknown): SessionTokens {
  if (!isRecord(raw)) {
    return { baseline: null, saved: null, spent: null }
  }

  return {
    baseline: numOrNull(raw.baseline) ?? numOrNull(raw.baseline_total),
    saved: numOrNull(raw.saved) ?? numOrNull(raw.saved_total),
    spent: numOrNull(raw.spent) ?? numOrNull(raw.actual_total)
  }
}

function parseEvent(raw: unknown, index: number): CockpitEvent | null {
  if (!isRecord(raw)) {
    return null
  }

  return {
    eventHash: strOrNull(raw.eventHash) ?? strOrNull(raw.event_hash),
    id: strOrNull(raw.eventId) ?? strOrNull(raw.event_id) ?? `event-${index}`,
    model: strOrNull(raw.model),
    prevEventHash: strOrNull(raw.prevEventHash) ?? strOrNull(raw.prev_event_hash),
    proofKind: isProofKind(raw.proofKind) ? raw.proofKind : isProofKind(raw.proof_kind) ? raw.proof_kind : null,
    provider: strOrNull(raw.provider),
    surfaces: Array.isArray(raw.surfaces) ? raw.surfaces.filter((v): v is string => typeof v === 'string') : [],
    taskTitle: strOrNull(raw.taskTitle) ?? strOrNull(raw.task_title),
    timestamp: strOrNull(raw.timestamp),
    tokens: parseTokens(raw.tokens)
  }
}

export function parseSessions(raw: unknown): CockpitSession[] {
  if (!Array.isArray(raw)) {
    return []
  }

  const sessions: CockpitSession[] = []

  for (const [index, entry] of raw.entries()) {
    if (!isRecord(entry)) {
      continue
    }

    const totals = parseTokens(entry.totals)
    const events = (Array.isArray(entry.events) ? entry.events : [])
      .map((event, i) => parseEvent(event, i))
      .filter((event): event is CockpitEvent => event !== null)

    sessions.push({
      branch: strOrNull(entry.branch),
      endedAt: strOrNull(entry.endedAt) ?? strOrNull(entry.ended_at),
      events,
      repo: strOrNull(entry.repo),
      runId: strOrNull(entry.runId) ?? strOrNull(entry.run_id) ?? `session-${index}`,
      savedPct:
        totals.saved !== null && totals.baseline !== null && totals.baseline > 0
          ? Math.round((totals.saved / totals.baseline) * 100)
          : null,
      startedAt: strOrNull(entry.startedAt) ?? strOrNull(entry.started_at),
      title: strOrNull(entry.title),
      totals
    })
  }

  return sessions
}

/** First 8 chars of a hash for chip display; null-tolerant. */
export function truncateHash(hash: null | string, length = 8): null | string {
  if (!hash) {
    return null
  }

  return hash.length <= length ? hash : hash.slice(0, length)
}

/** HH:MM local time for a timeline row; falls back to the raw string. */
export function eventTimeLabel(timestamp: null | string): null | string {
  if (!timestamp) {
    return null
  }

  const ms = Date.parse(timestamp)

  if (!Number.isFinite(ms)) {
    return timestamp
  }

  return new Intl.DateTimeFormat(undefined, { hour: '2-digit', minute: '2-digit' }).format(new Date(ms))
}

// ---------------------------------------------------------------------------
// Threshold crossing (Neon Burst trigger) — pure state machine
// ---------------------------------------------------------------------------

export interface ThresholdState {
  active: boolean
  /** Increments on each false→true crossing; keys a one-shot burst mount. */
  burstCount: number
}

export const INITIAL_THRESHOLD_STATE: ThresholdState = { active: false, burstCount: 0 }

/**
 * One step of the >=threshold state machine. Crossing up fires a new burst
 * (burstCount++); staying above keeps the current one; dropping below
 * re-arms so the next crossing fires again. `null` values never activate.
 */
export function nextThresholdState(prev: ThresholdState, value: null | number, threshold: number): ThresholdState {
  const above = value !== null && value >= threshold

  if (above && !prev.active) {
    return { active: true, burstCount: prev.burstCount + 1 }
  }

  if (!above && prev.active) {
    return { active: false, burstCount: prev.burstCount }
  }

  return prev
}
