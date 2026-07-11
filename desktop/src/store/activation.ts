/**
 * Durable install/activation contract shared by the installer and Desktop.
 *
 * This module intentionally contains no React or Electron dependencies.  The
 * renderer, bootstrap installer, and an eventual native bridge can all use
 * the same transition table and receipt gate.  `ready` is never inferred
 * from a process being alive or from the legacy onboarded marker: it requires
 * receipts from every trusted boundary.
 */

export const ACTIVATION_SCHEMA = 'simplicio.agent-activation/v1' as const

export const ACTIVATION_STATES = [
  'fresh',
  'checking',
  'needs_runtime',
  'needs_model',
  'needs_provider',
  'needs_permissions',
  'ready',
  'degraded',
  'repairing',
  'rolling_back',
  'failed'
] as const

/** Minimum non-destructive grants needed for the first verified task. */
export const REQUIRED_PERMISSIONS = ['workspace', 'terminal'] as const

export type ActivationState = (typeof ACTIVATION_STATES)[number]

export type ActivationReasonCode =
  | 'bootstrap_missing'
  | 'bootstrap_invalid'
  | 'runtime_missing'
  | 'runtime_incompatible'
  | 'handshake_missing'
  | 'handshake_not_ready'
  | 'migrations_failed'
  | 'neural_db_unavailable'
  | 'model_missing'
  | 'provider_missing'
  | 'permissions_missing'
  | 'smoke_failed'
  | 'first_task_missing'
  | 'first_task_failed'
  | 'permission_denied'
  | 'disk_low'
  | 'network_unavailable'
  | 'corrupt_state'
  | 'interrupted'
  | 'unknown'

export interface ActivationReceipt {
  kind: string
  id: string
  transactionId: string
  createdAt: string
  ok: boolean
  /** Redacted, bounded diagnostic information. */
  evidenceRef?: string
  version?: string
  hash?: string
  details?: Record<string, unknown>
}

export interface ActivationSnapshot {
  schema: typeof ACTIVATION_SCHEMA
  revision: number
  profileId: string
  state: ActivationState
  reasonCode: ActivationReasonCode | null
  blocking: boolean
  retryable: boolean
  nextAction: string
  transactionId: string | null
  receipts: ActivationReceipt[]
  /** Explicit opt-in only; never enabled by the production default. */
  capabilities: {
    model: 'local' | 'remote' | 'later' | null
    provider: string | null
    permissions: Record<string, boolean>
  }
  updatedAt: string
}

export interface ActivationEvidence {
  bootstrap?: ActivationReceipt
  handshake?: ActivationReceipt
  migrations?: ActivationReceipt
  neuralDb?: ActivationReceipt
  smoke?: ActivationReceipt
  firstTask?: ActivationReceipt
}

export type ActivationEvent =
  | { type: 'check_started' }
  | { type: 'bootstrap_started'; transactionId: string }
  | { type: 'bootstrap_receipt'; receipt: ActivationReceipt }
  | { type: 'handshake_receipt'; receipt: ActivationReceipt }
  | { type: 'runtime_missing'; reasonCode?: ActivationReasonCode }
  | { type: 'model_selected'; model: 'local' | 'remote' | 'later' }
  | { type: 'provider_selected'; provider: string }
  | { type: 'permission_granted'; permission: string }
  | { type: 'migration_receipt'; receipt: ActivationReceipt }
  | { type: 'neural_db_receipt'; receipt: ActivationReceipt }
  | { type: 'smoke_receipt'; receipt: ActivationReceipt }
  | { type: 'first_task_receipt'; receipt: ActivationReceipt }
  | { type: 'repair_started' }
  | { type: 'rollback_started' }
  | { type: 'failed'; reasonCode: ActivationReasonCode; retryable?: boolean; nextAction?: string }
  | { type: 'degraded'; reasonCode: ActivationReasonCode; nextAction: string }
  | { type: 'reset' }

const now = () => new Date().toISOString()

function receiptKind(receipt: ActivationReceipt, expected: string): boolean {
  return receipt.ok && receipt.kind === expected && Boolean(receipt.id) && Boolean(receipt.transactionId)
}

function hasReceipt(snapshot: ActivationSnapshot, kind: string): boolean {
  return snapshot.receipts.some(receipt => receiptKind(receipt, kind))
}

function addReceipt(snapshot: ActivationSnapshot, receipt: ActivationReceipt): ActivationSnapshot {
  const receipts = snapshot.receipts.filter(existing => existing.kind !== receipt.kind)
  return { ...snapshot, receipts: [...receipts, receipt] }
}

export function createActivationSnapshot(profileId: string, updatedAt = now()): ActivationSnapshot {
  return {
    schema: ACTIVATION_SCHEMA,
    revision: 0,
    profileId,
    state: 'fresh',
    reasonCode: null,
    blocking: true,
    retryable: true,
    nextAction: 'check',
    transactionId: null,
    receipts: [],
    capabilities: { model: null, provider: null, permissions: {} },
    updatedAt
  }
}

function update(snapshot: ActivationSnapshot, patch: Partial<ActivationSnapshot>): ActivationSnapshot {
  return { ...snapshot, ...patch, revision: snapshot.revision + 1, updatedAt: now() }
}

/** Strict final gate.  A ready process without these receipts is not ready. */
export function activationReady(snapshot: ActivationSnapshot): boolean {
  return (
    snapshot.state === 'ready' &&
    snapshot.reasonCode === null &&
    hasReceipt(snapshot, 'bootstrap') &&
    hasReceipt(snapshot, 'handshake') &&
    hasReceipt(snapshot, 'migrations') &&
    hasReceipt(snapshot, 'neural_db') &&
    hasReceipt(snapshot, 'smoke') &&
    hasReceipt(snapshot, 'first_task') &&
    snapshot.capabilities.model !== 'later' &&
    Boolean(snapshot.capabilities.provider) &&
    REQUIRED_PERMISSIONS.every(permission => snapshot.capabilities.permissions[permission] === true)
  )
}

export function reduceActivation(snapshot: ActivationSnapshot, event: ActivationEvent): ActivationSnapshot {
  switch (event.type) {
    case 'check_started':
      return update(snapshot, { state: 'checking', reasonCode: null, blocking: true, nextAction: 'preflight' })
    case 'bootstrap_started':
      return update(snapshot, {
        state: 'checking',
        transactionId: event.transactionId,
        reasonCode: null,
        blocking: true,
        nextAction: 'apply_bootstrap'
      })
    case 'bootstrap_receipt':
      return update(addReceipt(snapshot, event.receipt), { state: 'checking', nextAction: 'start_runtime' })
    case 'handshake_receipt':
      if (!receiptKind(event.receipt, 'handshake')) {
        return update(snapshot, { state: 'failed', reasonCode: 'handshake_not_ready', blocking: true, retryable: true, nextAction: 'retry_handshake' })
      }
      return update(addReceipt(snapshot, event.receipt), { state: 'checking', nextAction: 'verify_runtime' })
    case 'runtime_missing':
      return update(snapshot, { state: 'needs_runtime', reasonCode: event.reasonCode ?? 'runtime_missing', blocking: true, retryable: true, nextAction: 'install_runtime' })
    case 'model_selected':
      return update(snapshot, { capabilities: { ...snapshot.capabilities, model: event.model }, state: event.model === 'later' ? 'degraded' : 'needs_provider', reasonCode: event.model === 'later' ? 'model_missing' : null, blocking: event.model === 'later', nextAction: event.model === 'later' ? 'select_model' : 'select_provider' })
    case 'provider_selected':
      return update(snapshot, { capabilities: { ...snapshot.capabilities, provider: event.provider }, state: 'needs_permissions', reasonCode: null, blocking: true, nextAction: 'grant_permissions' })
    case 'permission_granted':
      return update(snapshot, { capabilities: { ...snapshot.capabilities, permissions: { ...snapshot.capabilities.permissions, [event.permission]: true } }, nextAction: 'verify_permissions' })
    case 'migration_receipt':
      return update(addReceipt(snapshot, event.receipt), { state: 'checking', reasonCode: null, nextAction: 'verify_neural_db' })
    case 'neural_db_receipt':
      return update(addReceipt(snapshot, event.receipt), { state: 'checking', reasonCode: null, nextAction: 'run_smoke' })
    case 'smoke_receipt':
      return update(addReceipt(snapshot, event.receipt), { state: 'checking', reasonCode: null, nextAction: 'run_first_task' })
    case 'first_task_receipt': {
      const next = addReceipt(snapshot, event.receipt)
      return activationReady({ ...next, state: 'ready' })
        ? update(next, { state: 'ready', reasonCode: null, blocking: false, retryable: false, nextAction: 'open_app' })
        : update(next, { state: 'needs_permissions', reasonCode: 'first_task_missing', blocking: true, retryable: true, nextAction: 'complete_activation' })
    }
    case 'repair_started':
      return update(snapshot, { state: 'repairing', reasonCode: null, blocking: true, retryable: true, nextAction: 'repair' })
    case 'rollback_started':
      return update(snapshot, { state: 'rolling_back', reasonCode: null, blocking: true, retryable: true, nextAction: 'rollback' })
    case 'degraded':
      return update(snapshot, { state: 'degraded', reasonCode: event.reasonCode, blocking: false, retryable: true, nextAction: event.nextAction })
    case 'failed':
      return update(snapshot, { state: 'failed', reasonCode: event.reasonCode, blocking: true, retryable: event.retryable ?? true, nextAction: event.nextAction ?? 'retry' })
    case 'reset':
      return createActivationSnapshot(snapshot.profileId)
  }
}

/** Recover an interrupted transaction without discarding confirmed receipts. */
export function resumeActivation(snapshot: ActivationSnapshot): ActivationSnapshot {
  if (snapshot.state === 'ready' && !activationReady(snapshot)) {
    return update(snapshot, { state: 'repairing', reasonCode: 'corrupt_state', blocking: true, retryable: true, nextAction: 'repair' })
  }
  if (snapshot.state === 'checking' || snapshot.state === 'repairing' || snapshot.state === 'rolling_back') {
    return update(snapshot, { state: 'checking', reasonCode: 'interrupted', blocking: true, retryable: true, nextAction: 'resume_transaction' })
  }
  return snapshot
}

export function parseActivationSnapshot(value: unknown): ActivationSnapshot | null {
  if (!value || typeof value !== 'object') return null
  const candidate = value as Partial<ActivationSnapshot>
  if (candidate.schema !== ACTIVATION_SCHEMA || typeof candidate.profileId !== 'string' || !ACTIVATION_STATES.includes(candidate.state as ActivationState)) return null
  if (!Array.isArray(candidate.receipts) || !candidate.capabilities || typeof candidate.revision !== 'number') return null
  return candidate as ActivationSnapshot
}

/** Two-phase localStorage persistence; committed is authoritative after crash. */
export function loadActivation(storage: Pick<Storage, 'getItem' | 'removeItem' | 'setItem'>, key: string): ActivationSnapshot | null {
  const decode = (raw: string | null): unknown => {
    if (!raw) return null
    try {
      return JSON.parse(raw)
    } catch {
      return null
    }
  }
  const committed = parseActivationSnapshot(decode(storage.getItem(key)))
  if (committed) return resumeActivation(committed)
  const pending = parseActivationSnapshot(decode(storage.getItem(`${key}.pending`)))
  return pending ? resumeActivation(pending) : null
}

export function persistActivation(storage: Pick<Storage, 'removeItem' | 'setItem'>, key: string, snapshot: ActivationSnapshot): void {
  const encoded = JSON.stringify(snapshot)
  storage.setItem(`${key}.pending`, encoded)
  storage.setItem(key, encoded)
  storage.removeItem(`${key}.pending`)
}
