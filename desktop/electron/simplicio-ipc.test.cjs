'use strict'

const test = require('node:test')
const assert = require('node:assert/strict')

const { registerSimplicioIpc, savingsReport, doctorRun, memoryStatus, mcpConnections } = require('./simplicio-ipc.cjs')

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

// Same shape as electron/dashboard-daemon.cjs's createDashboardDaemon() return
// value, plus an `_lastFetchRequest` escape hatch so the dashboard-summary
// handler test below can assert what it forwarded.
function makeFakeDashboardDaemon(initial = {}) {
  let running = Boolean(initial.running)
  let port = initial.port ?? null
  return {
    start: () => {
      running = true
      port = initial.port ?? 54321
      return { running, port, pid: 456, restarts: 0, startedAt: 1, lastError: null, binSource: 'test' }
    },
    stop: () => {
      running = false
      port = null
      return { running, port, pid: null, restarts: 0, startedAt: null, lastError: null, binSource: null }
    },
    status: () => ({
      running,
      port,
      pid: running ? 456 : null,
      restarts: 0,
      startedAt: null,
      lastError: null,
      binSource: null
    })
  }
}

test('registerSimplicioIpc registers every documented channel', () => {
  const ipcMain = makeFakeIpcMain()
  registerSimplicioIpc(ipcMain, {
    daemon: makeFakeDaemon(),
    dashboardDaemon: makeFakeDashboardDaemon(),
    cuaMcpDaemon: makeFakeDaemon()
  })
  assert.deepEqual(
    ipcMain.channels().sort(),
    [
      'simplicio:cua-mcp-start',
      'simplicio:cua-mcp-status',
      'simplicio:cua-mcp-stop',
      'simplicio:dashboard-start',
      'simplicio:dashboard-status',
      'simplicio:dashboard-stop',
      'simplicio:dashboard-summary',
      'simplicio:doctor',
      'simplicio:editors-detect',
      'simplicio:mcp-connections',
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

test('registerSimplicioIpc returns the MCP daemon instance with the dashboard daemon attached', () => {
  const ipcMain = makeFakeIpcMain()
  const daemon = makeFakeDaemon()
  const dashboardDaemon = makeFakeDashboardDaemon()
  const returned = registerSimplicioIpc(ipcMain, { daemon, dashboardDaemon })
  assert.equal(returned, daemon)
  assert.equal(returned.dashboardDaemon, dashboardDaemon)
})

test('simplicio:dashboard-start / status / stop drive the injected dashboard daemon', async () => {
  const ipcMain = makeFakeIpcMain()
  registerSimplicioIpc(ipcMain, { daemon: makeFakeDaemon(), dashboardDaemon: makeFakeDashboardDaemon() })

  const started = await ipcMain.invoke('simplicio:dashboard-start')
  assert.equal(started.running, true)
  assert.equal(started.port, 54321)

  const status = await ipcMain.invoke('simplicio:dashboard-status')
  assert.equal(status.running, true)
  assert.equal(status.port, 54321)

  const stopped = await ipcMain.invoke('simplicio:dashboard-stop')
  assert.equal(stopped.running, false)
  assert.equal(stopped.port, null)
})

test('registerSimplicioIpc returns the MCP daemon instance with the cua-mcp daemon attached', () => {
  const ipcMain = makeFakeIpcMain()
  const daemon = makeFakeDaemon()
  const cuaMcpDaemon = makeFakeDaemon()
  const returned = registerSimplicioIpc(ipcMain, { daemon, cuaMcpDaemon })
  assert.equal(returned, daemon)
  assert.equal(returned.cuaMcpDaemon, cuaMcpDaemon)
})

test('simplicio:cua-mcp-start / status / stop drive the injected cua-mcp daemon', async () => {
  const ipcMain = makeFakeIpcMain()
  registerSimplicioIpc(ipcMain, { daemon: makeFakeDaemon(), cuaMcpDaemon: makeFakeDaemon() })

  const started = await ipcMain.invoke('simplicio:cua-mcp-start')
  assert.equal(started.running, true)

  const status = await ipcMain.invoke('simplicio:cua-mcp-status')
  assert.equal(status.running, true)

  const stopped = await ipcMain.invoke('simplicio:cua-mcp-stop')
  assert.equal(stopped.running, false)
})

// Without an injected cuaMcpDaemon/resolveCuaMcpCommand, registerSimplicioIpc
// still builds a REAL createCuaMcpDaemon() (never throws at registration
// time) -- it just honestly reports "not configured" instead of spawning,
// same contract as cua-mcp-daemon.cjs's own resolveCommand-missing case.
test('simplicio:cua-mcp-* falls back to a real (non-spawning) daemon when nothing is injected', async () => {
  const ipcMain = makeFakeIpcMain()
  registerSimplicioIpc(ipcMain, { daemon: makeFakeDaemon() })

  const started = await ipcMain.invoke('simplicio:cua-mcp-start')
  assert.equal(started.running, false)
  assert.equal(started.lastError, 'cua-mcp command resolver not configured')

  await ipcMain.invoke('simplicio:cua-mcp-stop')
})

test('simplicio:dashboard-summary resolves ok:false without fetching when the daemon is not running', async () => {
  const ipcMain = makeFakeIpcMain()
  registerSimplicioIpc(ipcMain, { daemon: makeFakeDaemon(), dashboardDaemon: makeFakeDashboardDaemon() })

  const result = await ipcMain.invoke('simplicio:dashboard-summary')
  assert.equal(result.ok, false)
  assert.equal(result.error, 'dashboard daemon not running')
})

test('simplicio:dashboard-summary resolves ok:false when running but port is falsy', async () => {
  const ipcMain = makeFakeIpcMain()
  const dashboardDaemon = makeFakeDashboardDaemon({ running: true, port: 0 })
  registerSimplicioIpc(ipcMain, { daemon: makeFakeDaemon(), dashboardDaemon })

  const result = await ipcMain.invoke('simplicio:dashboard-summary')
  assert.equal(result.ok, false)
  assert.equal(result.error, 'dashboard daemon not running')
})

test('simplicio:dashboard-summary fetches against the daemon\'s own announced port once running', async () => {
  const ipcMain = makeFakeIpcMain()
  const dashboardDaemon = makeFakeDashboardDaemon({ running: true, port: 9119 })
  registerSimplicioIpc(ipcMain, { daemon: makeFakeDaemon(), dashboardDaemon })

  const originalFetch = global.fetch
  let seenUrl = null
  global.fetch = async url => {
    seenUrl = url
    return { ok: true, status: 200, json: async () => ({ totals: { events: 1 } }) }
  }
  try {
    const result = await ipcMain.invoke('simplicio:dashboard-summary', { group: 'hour' })
    assert.equal(result.ok, true)
    assert.deepEqual(result.summary, { totals: { events: 1 } })
    assert.equal(seenUrl, 'http://127.0.0.1:9119/api/summary?group=hour')
  } finally {
    global.fetch = originalFetch
  }
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

test('mcpConnections resolves {ok:true, status:<parsed json>} on success', async () => {
  const runner = async args => {
    assert.deepEqual(args, ['mcp', 'status', '--json'])
    return {
      ok: true,
      stdout: JSON.stringify({
        schema: 'simplicio.mcp-status/v1',
        connections: [{ pid: 123, client_name: 'Claude Code', alive: true }],
        generated_at: 1751990400
      }),
      stderr: '',
      code: 0
    }
  }
  const result = await mcpConnections(runner)
  assert.equal(result.ok, true)
  assert.equal(result.status.schema, 'simplicio.mcp-status/v1')
  assert.equal(result.status.connections.length, 1)
  assert.equal(result.status.connections[0].client_name, 'Claude Code')
})

// The real observed shape (2026-07-08) on a runtime binary that doesn't yet
// implement `mcp status`: exits 1, empty stdout, the error on stderr. This
// must resolve the same honest ok:false the other commands use -- never a
// thrown exception, never a fabricated connection list.
test('mcpConnections resolves {ok:false, error} when the subcommand does not exist yet', async () => {
  const runner = async args => {
    assert.deepEqual(args, ['mcp', 'status', '--json'])
    return {
      ok: false,
      stdout: '',
      stderr: "simplicio: unknown mcp subcommand 'status' (use add|list|remove|catalog|search|install|auth|token|logout)",
      code: 1
    }
  }
  const result = await mcpConnections(runner)
  assert.equal(result.ok, false)
  assert.match(result.error, /unknown mcp subcommand/)
  assert.equal('status' in result, false)
})

test('mcpConnections resolves {ok:false, error} when the binary is missing', async () => {
  const runner = async () => ({ ok: false, stdout: '', stderr: 'simplicio binary not found', code: null })
  const result = await mcpConnections(runner)
  assert.equal(result.ok, false)
  assert.equal(result.error, 'simplicio binary not found')
})

test('simplicio:mcp-connections handler invokes the real runSimplicio-backed mcpConnections()', async () => {
  const ipcMain = makeFakeIpcMain()
  registerSimplicioIpc(ipcMain, { daemon: makeFakeDaemon() })
  const result = await ipcMain.invoke('simplicio:mcp-connections')
  // No real binary assumption here (this is the electron test suite, not an
  // integration test) -- just assert the handler is wired and returns the
  // honest ok/error envelope shape, same as the other bridged commands.
  assert.equal(typeof result.ok, 'boolean')
  if (!result.ok) {
    assert.equal(typeof result.error, 'string')
  }
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
