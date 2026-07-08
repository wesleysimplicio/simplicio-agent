'use strict'

const test = require('node:test')
const assert = require('node:assert/strict')
const { EventEmitter } = require('node:events')

const { createCuaMcpDaemon } = require('./cua-mcp-daemon.cjs')
const { MIN_BACKOFF_MS } = require('./mcp-daemon.cjs')

// A fake spawn() that yields a controllable child EventEmitter for each call,
// recording every invocation (including the env/stdio options) for
// assertions. Mirrors makeFakeSpawn in mcp-daemon.test.cjs.
function makeFakeSpawn() {
  const children = []
  const spawnFn = (command, args, options) => {
    const child = new EventEmitter()
    child.stdout = new EventEmitter()
    child.stderr = new EventEmitter()
    child.stdin = new EventEmitter()
    child.stdin.ended = false
    child.stdin.end = () => {
      child.stdin.ended = true
    }
    child.pid = 7000 + children.length
    child.kill = () => child.emit('exit', null, 'SIGTERM')
    children.push({ command, args, options, child })
    return child
  }
  return { spawnFn, children }
}

// A deterministic fake scheduler so restart timing is driven by the test, not
// real timers -- setTimeout(...30000) in a unit test would be unacceptable.
function makeFakeScheduler() {
  const pending = []
  return {
    scheduleRestart: (fn, delay) => {
      const handle = { fn, delay, cancelled: false }
      pending.push(handle)
      return handle
    },
    clearScheduled: handle => {
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

const FAKE_RESOLVED = {
  command: '/hermes/venv/bin/python',
  args: ['-m', 'hermes_cli.main', 'mcp', 'serve'],
  env: { PATH: '/usr/bin', PYTHONPATH: '/hermes/hermes-agent' }
}

test('createCuaMcpDaemon.start spawns the resolved command and reports running status', () => {
  const { spawnFn, children } = makeFakeSpawn()
  const { scheduleRestart, clearScheduled } = makeFakeScheduler()
  const daemon = createCuaMcpDaemon({
    spawnFn,
    scheduleRestart,
    clearScheduled,
    resolveCommand: () => FAKE_RESOLVED
  })

  const status = daemon.start()
  assert.equal(status.running, true)
  assert.equal(status.pid, 7000)
  assert.equal(status.binSource, FAKE_RESOLVED.command)
  // ISO-8601 string, matching the CuaMcpDaemonStatus.startedAt contract
  // (mirrors McpDaemonStatus/DashboardStatus in src/global.d.ts).
  assert.equal(typeof status.startedAt, 'string')
  assert.equal(Number.isNaN(Date.parse(status.startedAt)), false)
  assert.equal(children.length, 1)
  assert.equal(children[0].command, FAKE_RESOLVED.command)
  assert.deepEqual(children[0].args, FAKE_RESOLVED.args)
  assert.deepEqual(children[0].options.env, FAKE_RESOLVED.env)
  daemon.stop()
})

test('createCuaMcpDaemon spawns with stdin as an open pipe and does not end it while running', () => {
  const { spawnFn, children } = makeFakeSpawn()
  const scheduler = makeFakeScheduler()
  const daemon = createCuaMcpDaemon({
    spawnFn,
    scheduleRestart: scheduler.scheduleRestart,
    clearScheduled: scheduler.clearScheduled,
    execFileSyncFn: () => {},
    resolveCommand: () => FAKE_RESOLVED
  })

  daemon.start()
  assert.deepEqual(children[0].options.stdio, ['pipe', 'pipe', 'pipe'], "stdin must be 'pipe', never 'ignore'")
  assert.equal(children[0].child.stdin.ended, false, 'stdin must stay open while supervising')

  // stop() is the ONLY place stdin gets ended (graceful EOF before the kill).
  daemon.stop()
  assert.equal(children[0].child.stdin.ended, true)
})

test('createCuaMcpDaemon status carries an explicit lastError when resolveCommand is not configured', () => {
  const scheduler = makeFakeScheduler()
  const daemon = createCuaMcpDaemon({
    scheduleRestart: scheduler.scheduleRestart,
    clearScheduled: scheduler.clearScheduled
  })
  const status = daemon.start()
  assert.equal(status.running, false)
  assert.equal(status.pid, null)
  assert.equal(status.lastError, 'cua-mcp command resolver not configured')
  daemon.stop()
})

test('createCuaMcpDaemon status carries an explicit lastError when resolveCommand() returns null, without throwing', () => {
  const scheduler = makeFakeScheduler()
  const daemon = createCuaMcpDaemon({
    scheduleRestart: scheduler.scheduleRestart,
    clearScheduled: scheduler.clearScheduled,
    resolveCommand: () => null
  })

  assert.doesNotThrow(() => daemon.start())
  const status = daemon.status()
  assert.equal(status.running, false)
  assert.equal(status.pid, null)
  assert.equal(status.lastError, 'cua-mcp command not resolved')
  daemon.stop()
})

test('createCuaMcpDaemon treats an unexpected clean exit (code 0) as a crash: descriptive lastError + restart', () => {
  const { spawnFn, children } = makeFakeSpawn()
  const scheduler = makeFakeScheduler()
  const daemon = createCuaMcpDaemon({
    spawnFn,
    scheduleRestart: scheduler.scheduleRestart,
    clearScheduled: scheduler.clearScheduled,
    execFileSyncFn: () => {},
    resolveCommand: () => FAKE_RESOLVED,
    now: () => 0
  })

  daemon.start()
  children[0].child.emit('exit', 0, null)

  const status = daemon.status()
  assert.equal(status.running, false)
  assert.match(status.lastError, /exited \(code 0\) unexpectedly/)
  assert.match(status.lastError, /stdin/i)
  assert.equal(status.restarts, 1)
  assert.deepEqual(scheduler.pendingDelays(), [MIN_BACKOFF_MS], 'code 0 must schedule a restart like any crash')

  scheduler.fireNext()
  assert.equal(children.length, 2, 'a replacement child must be spawned')
  assert.equal(daemon.status().running, true)
  daemon.stop()
})

test('createCuaMcpDaemon auto-restarts on unexpected exit with growing backoff, and stop() halts restarts', () => {
  const { spawnFn, children } = makeFakeSpawn()
  const scheduler = makeFakeScheduler()
  let clock = 0
  const daemon = createCuaMcpDaemon({
    spawnFn,
    scheduleRestart: scheduler.scheduleRestart,
    clearScheduled: scheduler.clearScheduled,
    resolveCommand: () => FAKE_RESOLVED,
    now: () => clock,
    // stop() below would otherwise shell out to a real `taskkill` on Windows.
    execFileSyncFn: () => {}
  })

  daemon.start()
  assert.equal(children.length, 1)

  // Crash immediately (well under the stable-uptime threshold).
  clock = 10
  children[0].child.emit('exit', 1, null)
  assert.equal(daemon.status().running, false)
  assert.equal(daemon.status().restarts, 1)
  assert.deepEqual(scheduler.pendingDelays(), [MIN_BACKOFF_MS])

  scheduler.fireNext()
  assert.equal(children.length, 2)
  assert.equal(daemon.status().running, true)

  // Crash again quickly -> backoff should double.
  clock = 20
  children[1].child.emit('exit', 1, null)
  assert.deepEqual(scheduler.pendingDelays(), [MIN_BACKOFF_MS * 2])

  scheduler.fireNext()
  assert.equal(children.length, 3)

  // stop() should cancel any pending restart and not spawn again.
  daemon.stop()
  children[2].child.emit('exit', 1, null)
  assert.deepEqual(scheduler.pendingDelays(), [])
  assert.equal(children.length, 3)
  assert.equal(daemon.status().running, false)
})

test('createCuaMcpDaemon resets backoff to MIN after a stable run', () => {
  const { spawnFn, children } = makeFakeSpawn()
  const scheduler = makeFakeScheduler()
  let clock = 0
  const daemon = createCuaMcpDaemon({
    spawnFn,
    scheduleRestart: scheduler.scheduleRestart,
    clearScheduled: scheduler.clearScheduled,
    resolveCommand: () => FAKE_RESOLVED,
    now: () => clock
  })

  daemon.start()
  clock = 5
  children[0].child.emit('exit', 1, null) // fast crash -> MIN_BACKOFF_MS
  assert.deepEqual(scheduler.pendingDelays(), [MIN_BACKOFF_MS])
  scheduler.fireNext()

  clock = 5 + 70000 // ran "stably" past STABLE_UPTIME_MS this time
  children[1].child.emit('exit', 1, null)
  assert.deepEqual(scheduler.pendingDelays(), [MIN_BACKOFF_MS])
  daemon.stop()
})

test('createCuaMcpDaemon.stop() kills the running child via taskkill on win32 and clears status', () => {
  const { spawnFn } = makeFakeSpawn()
  const scheduler = makeFakeScheduler()
  let killed = false
  const daemon = createCuaMcpDaemon({
    spawnFn,
    scheduleRestart: scheduler.scheduleRestart,
    clearScheduled: scheduler.clearScheduled,
    resolveCommand: () => FAKE_RESOLVED,
    execFileSyncFn: () => {
      killed = true
    }
  })

  daemon.start()
  const originalPlatform = Object.getOwnPropertyDescriptor(process, 'platform')
  Object.defineProperty(process, 'platform', { value: 'win32' })
  try {
    const status = daemon.stop()
    assert.equal(status.running, false)
    assert.equal(status.pid, null)
    assert.equal(killed, true)
  } finally {
    Object.defineProperty(process, 'platform', originalPlatform)
  }
})

test('createCuaMcpDaemon.stop() on a never-started daemon is a safe no-op', () => {
  const scheduler = makeFakeScheduler()
  const daemon = createCuaMcpDaemon({
    scheduleRestart: scheduler.scheduleRestart,
    clearScheduled: scheduler.clearScheduled,
    resolveCommand: () => FAKE_RESOLVED
  })

  const status = daemon.stop()
  assert.equal(status.running, false)
  assert.equal(status.pid, null)
})
