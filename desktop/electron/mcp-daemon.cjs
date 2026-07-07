'use strict'

/**
 * mcp-daemon.cjs
 *
 * Supervises a long-running `simplicio serve --mcp --stdio` child process so
 * the MCP server is "always active" for the desktop app: auto-restart on
 * exit/crash with exponential backoff, capped, and reset back to the fastest
 * retry once the process proves it can stay up for a while.
 *
 * The restart policy is pulled out as pure functions (nextBackoffMs /
 * isStableUptime) so it's unit-testable without spawning a real process. The
 * daemon itself is built with createMcpDaemon(), a factory that takes
 * injectable spawn/resolve/log dependencies — same DI pattern as
 * fs-read-dir.cjs / desktop-uninstall.cjs — so tests can drive it with a fake
 * spawnFn and never touch a real binary or timers.
 */

const { execFileSync, spawn } = require('node:child_process')
const { resolveSimplicioBin, buildSpawnInvocation } = require('./simplicio-bin.cjs')

const MIN_BACKOFF_MS = 1000
const MAX_BACKOFF_MS = 30000
// A child that stayed up this long is considered "stable" -- its next crash
// restarts the backoff ladder from MIN_BACKOFF_MS instead of continuing to
// double, so a rare/transient failure doesn't inherit a long delay from a
// crash loop that happened hours ago.
const STABLE_UPTIME_MS = 60000

/**
 * Pure backoff step: given the previous delay (ms, 0/undefined for "no
 * restart yet"), return the next delay -- doubling, capped at MAX_BACKOFF_MS.
 */
function nextBackoffMs(previousMs) {
  if (!previousMs || previousMs < MIN_BACKOFF_MS) return MIN_BACKOFF_MS
  return Math.min(previousMs * 2, MAX_BACKOFF_MS)
}

/** True when `uptimeMs` is long enough to reset the backoff ladder. */
function isStableUptime(uptimeMs) {
  return Number(uptimeMs) >= STABLE_UPTIME_MS
}

/** Windows-only: reap a PID's whole process tree (mirrors main.cjs's forceKillProcessTree). */
function forceKillProcessTree(pid, execFileSyncFn = execFileSync) {
  if (process.platform !== 'win32') return
  if (!Number.isInteger(pid) || pid <= 0) return
  try {
    execFileSyncFn('taskkill', ['/PID', String(pid), '/T', '/F'], { stdio: 'ignore', windowsHide: true })
  } catch {
    // Already gone, or no permission -- best effort.
  }
}

/**
 * Build a supervised MCP daemon. Returns `{ start, stop, status }`; nothing
 * spawns until start() is called.
 *
 * @param {object} [opts]
 * @param {Function} [opts.spawnFn] - child_process.spawn stand-in (tests).
 * @param {Function} [opts.execFileSyncFn] - child_process.execFileSync stand-in (tests).
 * @param {Function} [opts.resolveBin] - resolveSimplicioBin stand-in (tests).
 * @param {Function} [opts.log] - receives raw stdout/stderr chunks (string).
 * @param {Function} [opts.scheduleRestart] - (fn, delayMs) => timerHandle, defaults to setTimeout.
 * @param {Function} [opts.clearScheduled] - (timerHandle) => void, defaults to clearTimeout.
 * @param {Function} [opts.now] - clock stand-in (tests), defaults to Date.now.
 */
function createMcpDaemon(opts = {}) {
  const spawnFn = opts.spawnFn || spawn
  const execFileSyncFn = opts.execFileSyncFn || execFileSync
  const resolveBin = opts.resolveBin || resolveSimplicioBin
  const log = opts.log || (() => {})
  const scheduleRestart = opts.scheduleRestart || ((fn, delay) => setTimeout(fn, delay))
  const clearScheduled = opts.clearScheduled || (handle => clearTimeout(handle))
  const now = opts.now || (() => Date.now())

  let child = null
  let stopped = true
  let restartTimer = null
  let backoffMs = 0
  let state = {
    running: false,
    pid: null,
    restarts: 0,
    startedAt: null,
    lastError: null,
    binSource: null
  }

  function status() {
    return { ...state }
  }

  function spawnOnce() {
    if (stopped) return

    const resolved = resolveBin()
    if (!resolved) {
      state = { ...state, running: false, pid: null, lastError: 'simplicio binary not found' }
      return
    }

    // .cmd/.bat shims must be routed through cmd.exe — a direct spawn EINVALs
    // on Windows (CVE-2024-27980 mitigation). Real .exe binaries pass through.
    const invocation = buildSpawnInvocation(resolved.bin, ['serve', '--mcp', '--stdio'])

    let spawned
    try {
      spawned = spawnFn(invocation.command, invocation.args, {
        windowsHide: true,
        windowsVerbatimArguments: invocation.windowsVerbatimArguments,
        // stdin MUST be an open pipe held for the child's whole life: the
        // stdio MCP server reads requests from stdin, and 'ignore' hands it
        // a closed fd -- immediate EOF, clean exit code 0 right after start
        // (the "Stopped · exited (code 0)" E2E bug). We never write to it
        // and never call child.stdin.end() while supervising; only stop()
        // tears the child (and with it the pipe) down.
        stdio: ['pipe', 'pipe', 'pipe']
      })
    } catch (error) {
      state = { ...state, running: false, pid: null, lastError: error.message, binSource: resolved.source }
      scheduleNextRestart()
      return
    }

    child = spawned
    const startedAtMs = now()
    state = {
      running: true,
      pid: Number.isInteger(spawned.pid) ? spawned.pid : null,
      restarts: state.restarts,
      // Exposed as an ISO string (the renderer-facing contract for this
      // field); handleExit() below does its uptime math off startedAtMs.
      startedAt: new Date(startedAtMs).toISOString(),
      lastError: null,
      binSource: resolved.source
    }

    if (spawned.stdout) spawned.stdout.on('data', chunk => log(chunk.toString()))
    if (spawned.stderr) spawned.stderr.on('data', chunk => log(chunk.toString()))
    if (spawned.stdin) {
      // Hold the pipe open, but never let a late EPIPE (child died first)
      // become an uncaught 'error' that takes down the Electron main process.
      spawned.stdin.on('error', () => {})
    }

    // Node emits 'error' (spawn failure) and/or 'exit' for the same failed
    // child; guard so a single crash counts as exactly one restart.
    let settled = false
    spawned.once('error', error => {
      if (settled) return
      settled = true
      state = { ...state, running: false, lastError: error.message }
      handleExit(startedAtMs)
    })

    spawned.once('exit', (code, signal) => {
      if (settled) return
      settled = true
      // ANY exit while supervising is unexpected for a long-running server
      // and triggers the restart backoff -- including a clean code 0, which
      // for a stdio server almost always means its stdin reached EOF.
      const lastError = signal
        ? `killed (${signal})`
        : code === 0
          ? 'exited (code 0) unexpectedly — stdio server saw EOF on stdin?'
          : `exited (code ${code})`
      state = { ...state, running: false, lastError }
      handleExit(startedAtMs)
    })
  }

  function handleExit(startedAtMs) {
    child = null
    state = { ...state, pid: null }
    if (stopped) return

    const uptimeMs = now() - startedAtMs
    backoffMs = isStableUptime(uptimeMs) ? MIN_BACKOFF_MS : nextBackoffMs(backoffMs)
    state = { ...state, restarts: state.restarts + 1 }
    scheduleNextRestart()
  }

  function scheduleNextRestart() {
    if (stopped) return
    const delay = backoffMs || MIN_BACKOFF_MS
    restartTimer = scheduleRestart(() => {
      restartTimer = null
      spawnOnce()
    }, delay)
  }

  function start() {
    if (!stopped) return status()
    stopped = false
    backoffMs = 0
    spawnOnce()
    return status()
  }

  function stop() {
    stopped = true
    if (restartTimer) {
      clearScheduled(restartTimer)
      restartTimer = null
    }

    const dying = child
    child = null
    state = { ...state, running: false, pid: null }

    if (!dying) return status()

    // Graceful first: EOF on stdin is the idiomatic shutdown signal for a
    // stdio server (this is the ONLY place stdin is ever ended -- never
    // while supervising). The kill below reaps it if it doesn't oblige.
    try {
      if (dying.stdin) dying.stdin.end()
    } catch {
      // already gone
    }

    const pid = dying.pid
    if (process.platform === 'win32' && Number.isInteger(pid)) {
      forceKillProcessTree(pid, execFileSyncFn)
    } else {
      try {
        dying.kill('SIGTERM')
      } catch {
        // already gone
      }
    }
    return status()
  }

  return { start, stop, status }
}

module.exports = {
  createMcpDaemon,
  nextBackoffMs,
  isStableUptime,
  forceKillProcessTree,
  MIN_BACKOFF_MS,
  MAX_BACKOFF_MS,
  STABLE_UPTIME_MS
}
