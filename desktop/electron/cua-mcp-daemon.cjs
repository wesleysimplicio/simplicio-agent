'use strict'

/**
 * cua-mcp-daemon.cjs
 *
 * Supervises a long-running Python MCP server -- `python -m hermes_cli.main
 * mcp serve` -- exposing the computer-use (cua-driver) toolset over MCP
 * stdio, "always active" for the desktop app the same way mcp-daemon.cjs
 * keeps the Rust kernel's `simplicio serve --mcp --stdio` alive: auto-restart
 * on exit/crash with exponential backoff, capped, and reset back to the
 * fastest retry once the process proves it can stay up for a while.
 *
 * The restart policy (nextBackoffMs / isStableUptime / forceKillProcessTree /
 * MIN_BACKOFF_MS) is imported from mcp-daemon.cjs rather than reimplemented --
 * one restart policy for every supervised simplicio-adjacent child, Rust or
 * Python.
 *
 * Unlike mcp-daemon.cjs (which resolves + spawns a `simplicio` binary via
 * resolveSimplicioBin/buildSpawnInvocation, including the .cmd-shim EINVAL
 * workaround), this daemon spawns the SAME Python interpreter/venv/env the
 * desktop already uses for the Hermes backend -- there is no binary-on-PATH
 * resolution or shim to route around here, just a python executable path. So
 * resolution is fully injected via `resolveCommand()` (returns `{command,
 * args, env}`) instead: main.cjs supplies the real resolver (mirroring its
 * own backend-spawn python/venvRoot/pythonPathEntries resolution --
 * `resolveCuaMcpCommand()` beside `createActiveBackend()`), and tests inject
 * a fake. This also keeps simplicio-ipc.cjs (which owns this daemon) from
 * having to duplicate main.cjs's backend-resolution logic.
 */

const { execFileSync, spawn } = require('node:child_process')
const { nextBackoffMs, isStableUptime, forceKillProcessTree, MIN_BACKOFF_MS } = require('./mcp-daemon.cjs')

/**
 * Build a supervised cua-mcp daemon. Returns `{ start, stop, status }`;
 * nothing spawns until start() is called.
 *
 * @param {object} [opts]
 * @param {Function|null} [opts.resolveCommand] - () => {command, args, env} | null.
 *   The desktop's python/venv/env resolution, injected by the caller (main.cjs
 *   in production, a fake in tests). There is no default resolution -- a
 *   missing/null resolver, or one that returns a falsy value, is treated as
 *   an honest "not found" (lastError set, no throw, no fabricated command),
 *   same philosophy as resolveSimplicioBin() returning null.
 * @param {Function} [opts.spawnFn] - child_process.spawn stand-in (tests).
 * @param {Function} [opts.execFileSyncFn] - child_process.execFileSync stand-in (tests).
 * @param {Function} [opts.log] - receives raw stdout/stderr chunks (string).
 * @param {Function} [opts.scheduleRestart] - (fn, delayMs) => timerHandle, defaults to setTimeout.
 * @param {Function} [opts.clearScheduled] - (timerHandle) => void, defaults to clearTimeout.
 * @param {Function} [opts.now] - clock stand-in (tests), defaults to Date.now.
 */
function createCuaMcpDaemon(opts = {}) {
  const resolveCommand = opts.resolveCommand || null
  const spawnFn = opts.spawnFn || spawn
  const execFileSyncFn = opts.execFileSyncFn || execFileSync
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

    if (typeof resolveCommand !== 'function') {
      state = { ...state, running: false, pid: null, lastError: 'cua-mcp command resolver not configured' }
      return
    }

    const resolved = resolveCommand()
    if (!resolved || !resolved.command) {
      state = { ...state, running: false, pid: null, lastError: 'cua-mcp command not resolved' }
      return
    }

    let spawned
    try {
      spawned = spawnFn(resolved.command, resolved.args || [], {
        windowsHide: true,
        env: resolved.env,
        // stdin MUST be an open pipe held for the child's whole life: FastMCP
        // (the Python MCP server) reads requests from stdin, and 'ignore'
        // hands it a closed fd -- immediate EOF, clean exit code 0 right
        // after start (the same "Stopped · exited (code 0)" failure mode
        // mcp-daemon.cjs documents for the Rust stdio server). We never write
        // to it and never call child.stdin.end() while supervising; only
        // stop() tears the child (and with it the pipe) down.
        stdio: ['pipe', 'pipe', 'pipe']
      })
    } catch (error) {
      state = { ...state, running: false, pid: null, lastError: error.message, binSource: resolved.command }
      scheduleNextRestart()
      return
    }

    child = spawned
    const startedAtMs = now()
    state = {
      // FastMCP has no readiness port/announcement to wait for (unlike
      // dashboard-daemon.cjs's HTTP server) -- same as mcp-daemon.cjs's
      // stdio daemon, a successful spawn IS "running".
      running: true,
      pid: Number.isInteger(spawned.pid) ? spawned.pid : null,
      restarts: state.restarts,
      // Exposed as an ISO string, matching McpDaemonStatus/DashboardStatus's
      // startedAt convention (src/global.d.ts).
      startedAt: new Date(startedAtMs).toISOString(),
      lastError: null,
      binSource: resolved.command
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
  createCuaMcpDaemon
}
