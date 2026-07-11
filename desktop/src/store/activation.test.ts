import { describe, expect, it } from 'vitest'

import {
  activationReady,
  createActivationSnapshot,
  loadActivation,
  persistActivation,
  reduceActivation,
  resumeActivation,
  type ActivationReceipt
} from './activation'

const receipt = (kind: string): ActivationReceipt => ({
  kind,
  id: `${kind}-1`,
  transactionId: 'tx-1',
  createdAt: '2026-01-01T00:00:00.000Z',
  ok: true
})

function readySnapshot() {
  let state = createActivationSnapshot('profile-1')
  state = reduceActivation(state, { type: 'bootstrap_started', transactionId: 'tx-1' })
  state = reduceActivation(state, { type: 'bootstrap_receipt', receipt: receipt('bootstrap') })
  state = reduceActivation(state, { type: 'handshake_receipt', receipt: receipt('handshake') })
  state = reduceActivation(state, { type: 'model_selected', model: 'remote' })
  state = reduceActivation(state, { type: 'provider_selected', provider: 'anthropic' })
  for (const permission of ['workspace', 'terminal']) state = reduceActivation(state, { type: 'permission_granted', permission })
  state = reduceActivation(state, { type: 'migration_receipt', receipt: receipt('migrations') })
  state = reduceActivation(state, { type: 'neural_db_receipt', receipt: receipt('neural_db') })
  state = reduceActivation(state, { type: 'smoke_receipt', receipt: receipt('smoke') })
  state = reduceActivation(state, { type: 'first_task_receipt', receipt: receipt('first_task') })
  // The permission set is explicit and all granted permissions are true.
  return state
}

describe('activation contract', () => {
  it('does not reach ready from a process or provider marker alone', () => {
    const state = createActivationSnapshot('profile-1')
    expect(activationReady(state)).toBe(false)
    expect(reduceActivation(state, { type: 'provider_selected', provider: 'anthropic' }).state).toBe('needs_permissions')
  })

  it('requires bootstrap, handshake, migrations, neural DB, and first task receipts', () => {
    const state = readySnapshot()
    expect(state.state).toBe('ready')
    expect(state.reasonCode).toBeNull()
    expect(activationReady(state)).toBe(true)
  })

  it('preserves confirmed receipts and marks an interrupted transaction resumable', () => {
    let state = createActivationSnapshot('profile-1')
    state = reduceActivation(state, { type: 'bootstrap_started', transactionId: 'tx-1' })
    state = reduceActivation(state, { type: 'bootstrap_receipt', receipt: receipt('bootstrap') })
    const resumed = resumeActivation(state)
    expect(resumed.state).toBe('checking')
    expect(resumed.reasonCode).toBe('interrupted')
    expect(resumed.receipts).toHaveLength(1)
  })

  it('uses a two-phase commit and recovers pending state after a crash', () => {
    const values = new Map<string, string>()
    const storage = {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => values.set(key, value),
      removeItem: (key: string) => values.delete(key)
    }
    const state = createActivationSnapshot('profile-1')
    persistActivation(storage, 'activation', state)
    expect(loadActivation(storage, 'activation')?.profileId).toBe('profile-1')
    values.set('activation.pending', JSON.stringify({ ...state, revision: 2, state: 'checking' }))
    values.delete('activation')
    expect(loadActivation(storage, 'activation')?.state).toBe('checking')
  })
})
