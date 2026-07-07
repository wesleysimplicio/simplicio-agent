'use strict'

const test = require('node:test')
const assert = require('node:assert/strict')

const { registerSimplicioIpc, savingsReport, doctorRun, memoryStatus } = require('./simplicio-ipc.cjs')

// A minimal ipcMain fake: records handlers by channel and lets the test
// invoke them directly, so this doesn't need a real electron runtime.
function makeFakeIpcMain() {
  const handlers = new Map()
  return {
    handle: (channel, fn) => handlers.set(channel, fn),
    invoke: (channel, ...args) => {
      const fn = handlers.get(channel)
      assert.ok(fn, `no handler registered for ${channel}`)
      return fn({}, ...args)
    },
    channels: () => [...handlers.keys()]
  }
}

function makeFakeDaemon() {
  let running = false
  return {
    start: () => {
      running = true
      return { running, pid: 123, restarts: 0, startedAt: 1, lastError: null, binSource: 'test' }
    },
    stop: () => {
      running = false
      return { running, pid: null, restarts: 0, startedAt: null, lastError: null, binSource: null }
    },
    status: () => ({ running, pid: running ? 123 : null, restarts: 0, startedAt: null, lastError: null, binSource: null })
  }
}

test('registerSimplicioIpc registers every documented channel', () => {
  const ipcMain = makeFakeIpcMain()
  registerSimplicioIpc(ipcMain, { daemon: makeFakeDaemon() })
  assert.deepEqual(
    ipcMain.channels().sort(),
    [
      'simplicio:doctor',
      'simplicio:editors-detect',
      'simplicio:mcp-daemon-start',
      'simplicio:mcp-daemon-status',
      'simplicio:mcp-daemon-stop',
      'simplicio:mcp-register',
      'simplicio:memory-status',
      'simplicio:savings-report',
      'simplicio:savings-sessions'
    ].sort()
  )
})

test('simplicio:mcp-daemon-start / status / stop drive the injected daemon', async () => {
  const ipcMain = makeFakeIpcMain()
  registerSimplicioIpc(ipcMain, { daemon: makeFakeDaemon() })

  const started = await ipcMain.invoke('simplicio:mcp-daemon-start')
  assert.equal(started.running, true)

  const status = await ipcMain.invoke('simplicio:mcp-daemon-status')
  assert.equal(status.running, true)

  const stopped = await ipcMain.invoke('simplicio:mcp-daemon-stop')
  assert.equal(stopped.running, false)
})

test('simplicio:editors-detect returns ok:true with the real detectEditors() shape', async () => {
  const ipcMain = makeFakeIpcMain()
  registerSimplicioIpc(ipcMain, { daemon: makeFakeDaemon() })
  const result = await ipcMain.invoke('simplicio:editors-detect')
  assert.equal(result.ok, true)
  assert.ok(Array.isArray(result.editors))
  assert.ok(result.editors.length > 0)
  assert.ok('installed' in result.editors[0])
  assert.ok('registered' in result.editors[0])
})

test('registerSimplicioIpc returns the daemon instance', () => {
  const ipcMain = makeFakeIpcMain()
  const daemon = makeFakeDaemon()
  const returned = registerSimplicioIpc(ipcMain, { daemon })
  assert.equal(returned, daemon)
})

// The exact field name here (`report`, not `data`) is a deliberate contract
// match with `SimplicioSavingsBridge`/`SavingsReportResult` in
// src/app/savings/types.ts -- a parallel in-flight change whose bridge.ts
// reads `result.report`. A regression here would silently break that
// renderer wiring without either side's tests failing.
test('savingsReport resolves {ok:true, report:<parsed json>} on success', async () => {
  const runner = async args => {
    assert.deepEqual(args, ['savings', 'report', '--json'])
    return { ok: true, stdout: '{"total_saved":42}', stderr: '', code: 0 }
  }
  const result = await savingsReport(runner)
  assert.deepEqual(result, { ok: true, report: { total_saved: 42 } })
})

test('savingsReport resolves {ok:false, error} when the binary is not found', async () => {
  const runner = async () => ({ ok: false, stdout: '', stderr: 'simplicio binary not found', code: null })
  const result = await savingsReport(runner)
  assert.equal(result.ok, false)
  assert.equal(result.error, 'simplicio binary not found')
  assert.equal('report' in result, false)
})

// `doctor` (not `data`) is a deliberate contract match with the local
// DoctorRunResult type in src/components/onboarding/doctor-step.tsx (a
// parallel in-flight change reading `result.doctor`).
test('doctorRun resolves {ok:true, doctor:<parsed json>} on success', async () => {
  const runner = async args => {
    assert.deepEqual(args, ['doctor', '--json'])
    return { ok: true, stdout: '{"overall_status":"ok"}', stderr: '', code: 0 }
  }
  const result = await doctorRun(runner)
  assert.deepEqual(result, { ok: true, doctor: { overall_status: 'ok' } })
})

test('memoryStatus resolves {ok:true, memory} filtering JSONL progress lines from stdout', async () => {
  const stdout = [
    '{"schema":"simplicio.progress/v1","step":"scan"}',
    JSON.stringify({
      schema: 'simplicio.memory-backend/v1',
      status: 'ready',
      selected_backend: 'sqlite-fts5',
      initialized: true,
      operator_visibility: { memory: { memory_items: 1304 } },
      guardian_policy: {
        guardians: [
          { name: 'Isa', status: 'active', role: 'recall' },
          { name: 'Helo', status: 'idle', role: 'context' },
          { name: 'Levi', status: 'armed', role: 'external' }
        ]
      }
    })
  ].join('\n')
  const runner = async args => {
    assert.deepEqual(args, ['memory', 'status', '--json'])
    return { ok: true, stdout, stderr: '', code: 0 }
  }
  const result = await memoryStatus(runner)
  assert.equal(result.ok, true)
  assert.equal(result.memory.status, 'ready')
  assert.equal(result.memory.selected_backend, 'sqlite-fts5')
  assert.equal(result.memory.operator_visibility.memory.memory_items, 1304)
  assert.equal(result.memory.guardian_policy.guardians.length, 3)
})

test('memoryStatus resolves {ok:false, error} when the binary is missing', async () => {
  const runner = async () => ({ ok: false, stdout: '', stderr: 'simplicio binary not found', code: null })
  const result = await memoryStatus(runner)
  assert.equal(result.ok, false)
  assert.equal(result.error, 'simplicio binary not found')
  assert.equal('memory' in result, false)
})

test('simplicio:savings-sessions handler forwards the optional repoPath and returns the ledger shape', async () => {
  const ipcMain = makeFakeIpcMain()
  registerSimplicioIpc(ipcMain, { daemon: makeFakeDaemon() })
  // No repoPath: reads only the home ledger (whatever this machine has) --
  // assert the envelope shape, not machine-specific contents.
  const result = await ipcMain.invoke('simplicio:savings-sessions', undefined)
  assert.equal(typeof result.ok, 'boolean')
  assert.ok(Array.isArray(result.sessions))
  assert.equal(typeof result.skipped, 'number')
  assert.ok(Array.isArray(result.sources))
})
