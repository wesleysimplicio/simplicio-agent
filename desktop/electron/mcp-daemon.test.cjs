'use strict'

const test = require('node:test')
const assert = require('node:assert/strict')
const { EventEmitter } = require('node:events')

const { createMcpDaemon, nextBackoffMs, isStableUptime, MIN_BACKOFF_MS, MAX_BACKOFF_MS } = require('./mcp-daemon.cjs')
const { buildSpawnInvocation } = require('./simplicio-bin.cjs')

test('nextBackoffMs starts at MIN_BACKOFF_MS and doubles up to MAX_BACKOFF_MS', () => {
  assert.equal(nextBackoffMs(0), MIN_BACKOFF_MS)
  assert.equal(nextBackoffMs(undefined), MIN_BACKOFF_MS)
  assert.equal(nextBackoffMs(1000), 2000)
  assert.equal(nextBackoffMs(2000), 4000)
  assert.equal(nextBackoffMs(4000), 8000)
  assert.equal(nextBackoffMs(8000), 16000)
  assert.equal(nextBackoffMs(16000), MAX_BACKOFF_MS)
  assert.equal(nextBackoffMs(MAX_BACKOFF_MS), MAX_BACKOFF_MS)
  assert.equal(nextBackoffMs(20000), MAX_BACKOFF_MS)
})

test('isStableUptime is true at/above 60s, false below', () => {
  assert.equal(isStableUptime(60000), true)
  assert.equal(isStableUptime(70000), true)
  assert.equal(isStableUptime(59999), false)
  assert.equal(isStableUptime(0), false)
})

// A fake spawn() that yields a controllable child EventEmitter for each call,
// recording every invocation for assertions.
function makeFakeSpawn() {
  const children = []
  const spawnFn = (bin, args) => {
    const child = new EventEmitter()
    child.stdout = new EventEmitter()
    child.stderr = new EventEmitter()
    child.pid = 1000 + children.length
    child.kill = () => child.emit('exit', null, 'SIGTERM')
    children.push({ bin, args, child })
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

test('createMcpDaemon.start spawns "serve --mcp --stdio" and reports running status', () => {
  const { spawnFn, children } = makeFakeSpawn()
  const { scheduleRestart, clearScheduled } = makeFakeScheduler()
  const daemon = createMcpDaemon({
    spawnFn,
    scheduleRestart,
    clearScheduled,
    resolveBin: () => ({ bin: '/bin/simplicio', source: 'test' })
  })

  const status = daemon.start()
  assert.equal(status.running, true)
  assert.equal(status.pid, 1000)
  assert.equal(status.binSource, 'test')
  // ISO-8601 string, matching the McpDaemonStatus.startedAt contract in
  // src/app/savings/types.ts (a parallel in-flight consumer of this bridge).
  assert.equal(typeof status.startedAt, 'string')
  assert.equal(Number.isNaN(Date.parse(status.startedAt)), false)
  assert.equal(children.length, 1)
  assert.deepEqual(children[0].args, ['serve', '--mcp', '--stdio'])
})

// EINVAL regression: when resolution lands on a .cmd shim, the daemon's
// long-running spawn must go through the SAME cmd.exe wrapper as
// runSimplicio (buildSpawnInvocation), never a direct spawn of the shim.
// On Windows this asserts the cmd.exe /d /s /c form with args preserved; on
// POSIX buildSpawnInvocation is a passthrough and the assertion still holds.
test('createMcpDaemon routes a .cmd shim spawn through buildSpawnInvocation', () => {
  const shim = 'C:\\Users\\u\\.local\\bin\\simplicio.cmd'
  const daemonArgs = ['serve', '--mcp', '--stdio']
  const expected = buildSpawnInvocation(shim, daemonArgs)

  let seen = null
  const spawnFn = (command, args, options) => {
    seen = { command, args, windowsVerbatimArguments: options.windowsVerbatimArguments }
    const child = new EventEmitter()
    child.stdout = new EventEmitter()
    child.stderr = new EventEmitter()
    child.pid = 4321
    child.kill = () => {}
    return child
  }

  const daemon = createMcpDaemon({
    spawnFn,
    scheduleRestart: () => ({}),
    clearScheduled: () => {},
    execFileSyncFn: () => {},
    resolveBin: () => ({ bin: shim, source: 'local-bin' })
  })
  daemon.start()

  assert.deepEqual(seen, {
    command: expected.command,
    args: expected.args,
    windowsVerbatimArguments: expected.windowsVerbatimArguments
  })
  if (process.platform === 'win32') {
    assert.equal(/cmd\.exe$/i.test(seen.command), true, 'shim must be wrapped in cmd.exe on Windows')
    assert.deepEqual(seen.args.slice(0, 3), ['/d', '/s', '/c'])
    assert.match(seen.args[3], /simplicio\.cmd serve --mcp --stdio/)
    assert.equal(seen.windowsVerbatimArguments, true)
  }
  daemon.stop()
})

test('createMcpDaemon status carries an explicit lastError when the binary is not found', () => {
  const daemon = createMcpDaemon({
    resolveBin: () => null,
    scheduleRestart: () => ({}),
    clearScheduled: () => {}
  })
  const status = daemon.start()
  assert.equal(status.running, false)
  assert.equal(status.lastError, 'simplicio binary not found')
})

test('createMcpDaemon auto-restarts on unexpected exit with growing backoff, and stop() halts restarts', () => {
  const { spawnFn, children } = makeFakeSpawn()
  const scheduler = makeFakeScheduler()
  let clock = 0
  const daemon = createMcpDaemon({
    spawnFn,
    scheduleRestart: scheduler.scheduleRestart,
    clearScheduled: scheduler.clearScheduled,
    resolveBin: () => ({ bin: '/bin/simplicio', source: 'test' }),
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

test('createMcpDaemon resets backoff to MIN after a stable run', () => {
  const { spawnFn, children } = makeFakeSpawn()
  const scheduler = makeFakeScheduler()
  let clock = 0
  const daemon = createMcpDaemon({
    spawnFn,
    scheduleRestart: scheduler.scheduleRestart,
    clearScheduled: scheduler.clearScheduled,
    resolveBin: () => ({ bin: '/bin/simplicio', source: 'test' }),
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
})

test('createMcpDaemon.stop() kills the running child and clears status', () => {
  const { spawnFn, children } = makeFakeSpawn()
  const scheduler = makeFakeScheduler()
  let killed = false
  const daemon = createMcpDaemon({
    spawnFn,
    scheduleRestart: scheduler.scheduleRestart,
    clearScheduled: scheduler.clearScheduled,
    resolveBin: () => ({ bin: '/bin/simplicio', source: 'test' }),
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
