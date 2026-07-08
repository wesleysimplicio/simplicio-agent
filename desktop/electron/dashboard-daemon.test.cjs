'use strict'

const test = require('node:test')
const assert = require('node:assert/strict')
const { EventEmitter } = require('node:events')

const { createDashboardDaemon, fetchSummary, READY_LINE_RE } = require('./dashboard-daemon.cjs')
const { buildSpawnInvocation } = require('./simplicio-bin.cjs')
const { MIN_BACKOFF_MS } = require('./mcp-daemon.cjs')

// A fake spawn() that yields a controllable child EventEmitter for each call,
// recording every invocation (including the stdio options) for assertions.
// Mirrors makeFakeSpawn in mcp-daemon.test.cjs.
function makeFakeSpawn() {
  const children = []
  const spawnFn = (bin, args, options) => {
    const child = new EventEmitter()
    child.stdout = new EventEmitter()
    child.stderr = new EventEmitter()
    child.stdin = new EventEmitter()
    child.stdin.ended = false
    child.stdin.end = () => {
      child.stdin.ended = true
    }
    child.pid = 2000 + children.length
    child.kill = () => child.emit('exit', null, 'SIGTERM')
    children.push({ bin, args, options, child })
    return child
  }
  return { spawnFn, children }
}

// A deterministic fake scheduler so restart/ready timing is driven by the
// test, not real timers.
function makeFakeScheduler() {
  const pending = []
  return {
    schedule: (fn, delay) => {
      const handle = { fn, delay, cancelled: false }
      pending.push(handle)
      return handle
    },
    clear: handle => {
      handle.cancelled = true
    },
    fireNext() {
      const handle = pending.shift()
      if (!handle || handle.cancelled) return null
      handle.fn()
      return handle
    },
    pendingDelays: () => pending.filter(h => !h.cancelled).map(h => h.delay)
  }
}

function makeDaemon(overrides = {}) {
  const { spawnFn, children } = overrides.spawn || makeFakeSpawn()
  const restartScheduler = overrides.restartScheduler || makeFakeScheduler()
  const readyScheduler = overrides.readyScheduler || makeFakeScheduler()
  const daemon = createDashboardDaemon({
    spawnFn,
    scheduleRestart: restartScheduler.schedule,
    clearScheduled: restartScheduler.clear,
    scheduleReadyTimeout: readyScheduler.schedule,
    clearReadyTimeout: readyScheduler.clear,
    execFileSyncFn: () => {},
    resolveBin: () => ({ bin: '/bin/simplicio', source: 'test' }),
    ...overrides.daemonOpts
  })
  return { daemon, children, restartScheduler, readyScheduler }
}

// ---------------------------------------------------------------------------
// spawn / stdio / args
// ---------------------------------------------------------------------------

test('createDashboardDaemon.start spawns "web-dashboard start --port 0 --no-open --json"', () => {
  const { daemon, children } = makeDaemon()
  const status = daemon.start()
  assert.equal(status.pid, 2000)
  assert.equal(status.binSource, 'test')
  assert.equal(status.running, false, 'not running until the ready line arrives')
  assert.equal(children.length, 1)
  assert.deepEqual(children[0].args, ['web-dashboard', 'start', '--port', '0', '--no-open', '--json'])
})

test('createDashboardDaemon spawns with stdin as an open pipe and does not end it while running', () => {
  const { daemon, children } = makeDaemon()
  daemon.start()
  assert.deepEqual(children[0].options.stdio, ['pipe', 'pipe', 'pipe'], "stdin must be 'pipe', never 'ignore'")
  assert.equal(children[0].child.stdin.ended, false, 'stdin must stay open while supervising')
  daemon.stop()
  assert.equal(children[0].child.stdin.ended, true)
})

test('createDashboardDaemon routes a .cmd shim spawn through buildSpawnInvocation', () => {
  const shim = 'C:\\Users\\u\\.local\\bin\\simplicio.cmd'
  const expected = buildSpawnInvocation(shim, ['web-dashboard', 'start', '--port', '0', '--no-open', '--json'])

  let seen = null
  const spawnFn = (command, args, options) => {
    seen = { command, args, windowsVerbatimArguments: options.windowsVerbatimArguments }
    const child = new EventEmitter()
    child.stdout = new EventEmitter()
    child.stderr = new EventEmitter()
    child.pid = 5555
    child.kill = () => {}
    return child
  }

  const { daemon } = makeDaemon({ spawn: { spawnFn, children: [] }, daemonOpts: { resolveBin: () => ({ bin: shim, source: 'local-bin' }) } })
  daemon.start()

  assert.deepEqual(seen, {
    command: expected.command,
    args: expected.args,
    windowsVerbatimArguments: expected.windowsVerbatimArguments
  })
  if (process.platform === 'win32') {
    assert.equal(/cmd\.exe$/i.test(seen.command), true)
    assert.match(seen.args[3], /simplicio\.cmd web-dashboard start --port 0 --no-open --json/)
  }
  daemon.stop()
})

test('createDashboardDaemon status carries an explicit lastError when the binary is not found', () => {
  const { restartScheduler } = { restartScheduler: makeFakeScheduler() }
  const daemon = createDashboardDaemon({
    resolveBin: () => null,
    scheduleRestart: restartScheduler.schedule,
    clearScheduled: restartScheduler.clear
  })
  const status = daemon.start()
  assert.equal(status.running, false)
  assert.equal(status.port, null)
  assert.equal(status.lastError, 'simplicio binary not found')
})

// ---------------------------------------------------------------------------
// SIMPLICIO_DASHBOARD_READY port=<N> parsing
// ---------------------------------------------------------------------------

test('READY_LINE_RE matches the exact runtime announcement', () => {
  assert.equal(READY_LINE_RE.test('SIMPLICIO_DASHBOARD_READY port=54321'), true)
  const m = 'SIMPLICIO_DASHBOARD_READY port=9119'.match(READY_LINE_RE)
  assert.equal(m[1], '9119')
})

test('status flips to running with the announced port once the ready line arrives', () => {
  const { daemon, children, readyScheduler } = makeDaemon()
  daemon.start()
  assert.equal(daemon.status().running, false)

  children[0].child.stdout.emit('data', 'SIMPLICIO_DASHBOARD_READY port=54321\n')

  const status = daemon.status()
  assert.equal(status.running, true)
  assert.equal(status.port, 54321)
  assert.equal(status.lastError, null)
  // The ready timeout must be cancelled once announced -- no dangling timer.
  assert.deepEqual(readyScheduler.pendingDelays(), [])
  daemon.stop()
})

test('ready line survives a log prefix before it and other lines before/after', () => {
  const { daemon, children } = makeDaemon()
  daemon.start()
  children[0].child.stdout.emit(
    'data',
    'Dashboard started at http://127.0.0.1:54321/\nSIMPLICIO_DASHBOARD_READY port=54321\nPress Ctrl+C to stop.\n'
  )
  const status = daemon.status()
  assert.equal(status.running, true)
  assert.equal(status.port, 54321)
  daemon.stop()
})

test('ready line split across multiple stdout chunks is still parsed', () => {
  const { daemon, children } = makeDaemon()
  daemon.start()
  children[0].child.stdout.emit('data', 'SIMPLICIO_DASHBOARD_READY po')
  children[0].child.stdout.emit('data', 'rt=8080\n')
  assert.equal(daemon.status().port, 8080)
  assert.equal(daemon.status().running, true)
  daemon.stop()
})

test('a second occurrence of the ready line (e.g. after a later restart) does not reprocess once announced', () => {
  const { daemon, children } = makeDaemon()
  daemon.start()
  children[0].child.stdout.emit('data', 'SIMPLICIO_DASHBOARD_READY port=1111\n')
  children[0].child.stdout.emit('data', 'SIMPLICIO_DASHBOARD_READY port=2222\n')
  assert.equal(daemon.status().port, 1111, 'first announcement wins for this child instance')
  daemon.stop()
})

test('no ready line within the timeout sets an explicit lastError, without touching pid/running', () => {
  const { daemon, children, readyScheduler } = makeDaemon()
  daemon.start()
  assert.equal(readyScheduler.pendingDelays().length, 1)

  readyScheduler.fireNext()

  const status = daemon.status()
  assert.equal(status.running, false)
  assert.equal(status.lastError, 'dashboard did not announce a port')
  assert.equal(status.pid, children[0].child.pid, 'the child is still alive, just unproven')
  daemon.stop()
})

test('a late ready line after the timeout still updates status (no exit happened)', () => {
  const { daemon, children, readyScheduler } = makeDaemon()
  daemon.start()
  readyScheduler.fireNext()
  assert.equal(daemon.status().lastError, 'dashboard did not announce a port')

  children[0].child.stdout.emit('data', 'SIMPLICIO_DASHBOARD_READY port=4321\n')
  const status = daemon.status()
  assert.equal(status.running, true)
  assert.equal(status.port, 4321)
  assert.equal(status.lastError, null)
  daemon.stop()
})

// ---------------------------------------------------------------------------
// restart / backoff / exit handling
// ---------------------------------------------------------------------------

test('an unexpected exit clears running/port and schedules a restart with growing backoff', () => {
  const { daemon, children, restartScheduler } = makeDaemon({ daemonOpts: { now: () => 0 } })
  daemon.start()
  children[0].child.stdout.emit('data', 'SIMPLICIO_DASHBOARD_READY port=54321\n')
  assert.equal(daemon.status().running, true)

  children[0].child.emit('exit', 1, null)
  const status = daemon.status()
  assert.equal(status.running, false)
  assert.equal(status.port, null)
  assert.equal(status.pid, null)
  assert.match(status.lastError, /exited \(code 1\)/)
  assert.equal(status.restarts, 1)
  assert.deepEqual(restartScheduler.pendingDelays(), [MIN_BACKOFF_MS])

  restartScheduler.fireNext()
  assert.equal(children.length, 2, 'a replacement child must be spawned')
  daemon.stop()
})

test('stop() cancels the pending ready timer, kills the child via taskkill on win32, and clears status', () => {
  const restartScheduler = makeFakeScheduler()
  const readyScheduler = makeFakeScheduler()
  let killed = false
  const { spawnFn } = makeFakeSpawn()
  const daemon = createDashboardDaemon({
    spawnFn,
    scheduleRestart: restartScheduler.schedule,
    clearScheduled: restartScheduler.clear,
    scheduleReadyTimeout: readyScheduler.schedule,
    clearReadyTimeout: readyScheduler.clear,
    resolveBin: () => ({ bin: '/bin/simplicio', source: 'test' }),
    execFileSyncFn: () => {
      killed = true
    }
  })

  const originalPlatform = Object.getOwnPropertyDescriptor(process, 'platform')
  Object.defineProperty(process, 'platform', { value: 'win32' })
  try {
    daemon.start()
    assert.equal(readyScheduler.pendingDelays().length, 1)

    const status = daemon.stop()
    assert.equal(status.running, false)
    assert.equal(status.pid, null)
    assert.equal(status.port, null)
    assert.equal(killed, true)
  } finally {
    Object.defineProperty(process, 'platform', originalPlatform)
  }
  assert.deepEqual(readyScheduler.pendingDelays(), [])
  assert.deepEqual(restartScheduler.pendingDelays(), [])
})

test('stop() halts further restarts after a crash', () => {
  const { daemon, children, restartScheduler } = makeDaemon()
  daemon.start()
  children[0].child.emit('exit', 1, null)
  assert.equal(restartScheduler.pendingDelays().length, 1)
  daemon.stop()
  assert.deepEqual(restartScheduler.pendingDelays(), [])
})

// ---------------------------------------------------------------------------
// fetchSummary
// ---------------------------------------------------------------------------

test('fetchSummary rejects an invalid port without calling fetch', async () => {
  let called = false
  const result = await fetchSummary(0, {}, { fetchFn: async () => { called = true } })
  assert.equal(result.ok, false)
  assert.match(result.error, /invalid dashboard port/)
  assert.equal(called, false)
})

test('fetchSummary builds the querystring from from/to/group and parses JSON on success', async () => {
  let seenUrl = null
  const fetchFn = async url => {
    seenUrl = url
    return {
      ok: true,
      status: 200,
      json: async () => ({ schema: 'simplicio.savings-dashboard-api/v1', totals: { events: 3 } })
    }
  }
  const result = await fetchSummary(54321, { from: 1000, to: 2000, group: 'day' }, { fetchFn })
  assert.equal(result.ok, true)
  assert.deepEqual(result.summary, { schema: 'simplicio.savings-dashboard-api/v1', totals: { events: 3 } })
  assert.equal(seenUrl, 'http://127.0.0.1:54321/api/summary?from=1000&to=2000&group=day')
})

test('fetchSummary omits unset params from the querystring', async () => {
  let seenUrl = null
  const fetchFn = async url => {
    seenUrl = url
    return { ok: true, status: 200, json: async () => ({}) }
  }
  await fetchSummary(9119, {}, { fetchFn })
  assert.equal(seenUrl, 'http://127.0.0.1:9119/api/summary')
})

test('fetchSummary surfaces a non-2xx response as ok:false with the status', async () => {
  const fetchFn = async () => ({ ok: false, status: 500 })
  const result = await fetchSummary(54321, {}, { fetchFn })
  assert.equal(result.ok, false)
  assert.match(result.error, /HTTP 500/)
})

test('fetchSummary surfaces a network error as ok:false', async () => {
  const fetchFn = async () => {
    throw new Error('ECONNREFUSED')
  }
  const result = await fetchSummary(54321, {}, { fetchFn })
  assert.equal(result.ok, false)
  assert.match(result.error, /ECONNREFUSED/)
})

test('fetchSummary aborts and reports a timeout when fetch never settles', async () => {
  let sawAbort = false
  const fetchFn = (url, { signal }) =>
    new Promise((resolve, reject) => {
      signal.addEventListener('abort', () => {
        sawAbort = true
        const err = new Error('aborted')
        err.name = 'AbortError'
        reject(err)
      })
    })
  const result = await fetchSummary(54321, {}, { fetchFn, timeoutMs: 10 })
  assert.equal(result.ok, false)
  assert.match(result.error, /timed out after 10ms/)
  assert.equal(sawAbort, true)
})
