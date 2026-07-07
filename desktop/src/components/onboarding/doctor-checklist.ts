// Pure mapping from a `simplicio doctor --json` payload to the onboarding
// "Pendências do runtime" checklist. Kept free of React/DOM so it can be
// unit-tested directly (see doctor-checklist.test.ts).
//
// The doctor JSON schema (simplicio-runtime `src/commands/doctor.rs`) is not
// guaranteed stable across runtime versions, and the desktop bridge that
// exposes it may not even be wired up on a given build (see the guard in
// doctor-step.tsx). Every field access below is defensive: an absent or
// malformed field renders as an "unknown" item — it is never invented.

export type DoctorItemStatus = 'error' | 'ok' | 'unknown' | 'warning'

export interface DoctorChecklistItem {
  detail: string
  /** Only set for non-ok/unknown items — a short, actionable repair hint. */
  fixHint?: string
  id: string
  status: DoctorItemStatus
  title: string
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function asNonEmptyString(value: unknown): null | string {
  return typeof value === 'string' && value.trim().length > 0 ? value : null
}

function asBoolean(value: unknown): boolean | null {
  return typeof value === 'boolean' ? value : null
}

const KNOWN_STATUSES: readonly string[] = ['ok', 'warning', 'error']

function normalizeStatus(value: unknown): DoctorItemStatus {
  return typeof value === 'string' && KNOWN_STATUSES.includes(value) ? (value as DoctorItemStatus) : 'unknown'
}

// health.checks[] entries use "info" as a fourth status in the runtime's own
// vocabulary (DoctorCheck.status: "ok" | "info" | "warning" | "error"). Fold
// it into "ok" for the checklist's 4-state UI — informational, not
// actionable.
function normalizeHealthCheckStatus(value: unknown): DoctorItemStatus {
  return value === 'info' ? 'ok' : normalizeStatus(value)
}

interface RawHealthCheck {
  detail?: unknown
  name?: unknown
  status?: unknown
}

// Finds the first `health.checks[]` entry whose `name` matches one of
// `names`, tried in order. Returns null when `health`/`checks` is absent or
// malformed, or none of the names are present — never throws.
function findHealthCheck(doctor: Record<string, unknown>, names: string[]): null | RawHealthCheck {
  const health = doctor.health

  if (!isRecord(health) || !Array.isArray(health.checks)) {
    return null
  }

  for (const name of names) {
    const found = health.checks.find(entry => isRecord(entry) && asNonEmptyString(entry.name) === name)

    if (found) {
      return found as RawHealthCheck
    }
  }

  return null
}

/**
 * Maps an already-parsed `simplicio doctor --json` payload into a small,
 * fixed set of checklist items for the onboarding "runtime pendencies" step:
 * binary path, runtime version, overall status, configured local model, and
 * (best-effort) memory/repo state. Accepts `unknown` because the payload
 * crosses an untyped preload bridge.
 */
export function mapDoctorToChecklist(doctor: unknown): DoctorChecklistItem[] {
  if (!isRecord(doctor)) {
    return []
  }

  const execution = isRecord(doctor.execution) ? doctor.execution : {}
  const policy = isRecord(doctor.policy) ? doctor.policy : {}

  const items: DoctorChecklistItem[] = []

  // 1. Runtime binary — where `simplicio` resolved to.
  const binaryPath = asNonEmptyString(execution.binary)

  items.push(
    binaryPath
      ? { id: 'binary', title: 'Binário do runtime', detail: binaryPath, status: 'ok' }
      : {
          id: 'binary',
          title: 'Binário do runtime',
          detail: 'Não foi possível localizar o binário do runtime.',
          status: 'unknown',
          fixHint: 'Instale o runtime simplicio e/ou defina a variável de ambiente SIMPLICIO_BIN.'
        }
  )

  // 2. Runtime version.
  const version = asNonEmptyString(doctor.version)

  items.push(
    version
      ? { id: 'version', title: 'Versão do runtime', detail: version, status: 'ok' }
      : { id: 'version', title: 'Versão do runtime', detail: 'Versão não reportada.', status: 'unknown' }
  )

  // 3. Overall status.
  const overallRaw = asNonEmptyString(doctor.overall_status)
  const overallStatus = normalizeStatus(overallRaw)

  items.push({
    id: 'overall',
    title: 'Status geral',
    detail: overallRaw ?? 'Não reportado.',
    status: overallStatus,
    fixHint:
      overallStatus === 'error'
        ? 'Rode `simplicio doctor --repair` em um terminal para tentar corrigir automaticamente.'
        : overallStatus === 'warning'
          ? 'Rode `simplicio doctor` em um terminal para ver os avisos em detalhe.'
          : undefined
  })

  // 4. Configured local model (policy.model / policy.local).
  const model = asNonEmptyString(policy.model)
  const isLocal = asBoolean(policy.local)

  items.push(
    model
      ? {
          id: 'model',
          title: 'Modelo local configurado',
          detail: isLocal === true ? `${model} (local)` : isLocal === false ? `${model} (remoto)` : model,
          status: 'ok'
        }
      : {
          id: 'model',
          title: 'Modelo local configurado',
          detail: 'Nenhum modelo configurado.',
          status: 'warning',
          fixHint: 'Configure um modelo em Configurações → Modelo, ou defina a variável SIMPLICIO_MODEL.'
        }
  )

  // 5. Memory / repo state — best-effort, sourced from health.checks[] when
  // present (tries the git/repo check first, then the runtime-home check).
  // Renders as unknown rather than inventing a state when neither is present.
  const repoCheck = findHealthCheck(doctor, ['git', 'runtime-home'])
  const repoStatus = repoCheck ? normalizeHealthCheckStatus(repoCheck.status) : 'unknown'

  items.push(
    repoCheck
      ? {
          id: 'repoState',
          title: 'Memória / estado do repositório',
          detail: asNonEmptyString(repoCheck.detail) ?? 'Sem detalhes.',
          status: repoStatus,
          fixHint:
            repoStatus !== 'ok' ? 'Rode `simplicio doctor --repair` em um terminal para tentar corrigir automaticamente.' : undefined
        }
      : {
          id: 'repoState',
          title: 'Memória / estado do repositório',
          detail: 'Não reportado por esta versão do runtime.',
          status: 'unknown'
        }
  )

  return items
}
