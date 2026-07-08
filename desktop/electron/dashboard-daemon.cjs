'use strict'

/**
 * dashboard-daemon.cjs
 *
 * Supervises `simplicio dashboard start --port 0 --no-open --json`, the
 * runtime's embedded token-savings dashboard HTTP server -- same supervision
 * pattern as mcp-daemon.cjs: spawn via resolveSimplicioBin/
 * buildSpawnInvocation (never a duplicate resolution path), stdin held open
 * as a pipe for the child's whole life, auto-restart on exit/crash with
 * exponential backoff, clean stop() with the Windows process-tree kill. The
 * backoff/uptime primitives (nextBackoffMs / isStableUptime /
 * forceKillProcessTree) are imported from mcp-daemon.cjs rather than
 * reimplemented -- one restart policy for every supervised simplicio child.
 *
 * On top of that shared pattern, this daemon watches stdout for the
 * `SIMPLICIO_DASHBOARD_READY port=<N>` line the runtime prints once its
 * HTTP listener is bound (src/dashboard_command.rs, dashboard_command()
 * "start" arm -- MANDATORY stdout announce, emitted in both --json and human
 * mode, on its own newline-terminated line). Until that line arrives,
 * status().running stays false even though a child process is alive; ~15s
 * without it is treated the same as any other supervision failure (lastError
 * set to an explicit "dashboard did not announce a port", matching the
 * codebase's "never fabricate readiness" contract -- e.g.
 * probeSimplicioBin's live --help gate in simplicio-bin.cjs).
 */

const { execFileSync, spawn } = require('node:child_process')
const { resolveSimplicioBin, buildSpawnInvocation } = require('./simplicio-bin.cjs')
const { nextBackoffMs, isStableUptime, forceKillProcessTree, MIN_BACKOFF_MS } = require('./mcp-daemon.cjs')

// Matches the exact contract documented at dashboard_command.rs:1870-1875 --
// "own newline-terminated line", present in both --json and human output.
const READY_LINE_RE = /^SIMPLICIO_DASHBOARD_READY port=(\d+)/m

// A cold JIT/AV-scan start is comparable to the MCP daemon's own spawn, not
// to the Python backend's multi-second uvicorn import chain (backend-ready.cjs
// budgets 90s for that) -- the dashboard is a stdlib-only Rust HTTP server
// that binds its socket before printing anything else. 15s is generous
// headroom over a warm start while still failing fast on a genuinely wedged
// binary.
const DEFAULT_READY_TIMEOUT_MS = 15000

/**
 * Build a supervised dashboard daemon. Returns `{ start, stop, status,
 * fetchSummary }`; nothing spawns until start() is called.
 *
 * @param {object} [opts]
 * @param {Function} [opts.spawnFn] - child_process.spawn stand-in (tests).
 * @param {Function} [opts.execFileSyncFn] - child_process.execFileSync stand-in (tests).
 * @param {Function} [opts.resolveBin] - resolveSimplicioBin stand-in (tests).
 * @param {Function} [opts.log] - receives raw stdout/stderr chunks (string).
 * @param {Function} [opts.scheduleRestart] - (fn, delayMs) => timerHandle, defaults to setTimeout.
 * @param {Function} [opts.clearScheduled] - (timerHandle) => void, defaults to clearTimeout.
 * @param {Function} [opts.scheduleReadyTimeout] - (fn, delayMs) => timerHandle, defaults to setTimeout.
 * @param {Function} [opts.clearReadyTimeout] - (timerHandle) => void, defaults to clearTimeout.
 * @param {Function} [opts.now] - clock stand-in (tests), defaults to Date.now.
 * @param {number} [opts.readyTimeoutMs] - how long to wait for the ready line before flagging lastError.
 */
function createDashboardDaemon(opts = {}) {
  const spawnFn = opts.spawnFn || spawn
  const execFileSyncFn = opts.execFileSyncFn || execFileSync
  const resolveBin = opts.resolveBin || resolveSimplicioBin
  const log = opts.log || (() => {})
  const scheduleRestart = opts.scheduleRestart || ((fn, delay) => setTimeout(fn, delay))
  const clearScheduled = opts.clearScheduled || (handle => clearTimeout(handle))
  const scheduleReadyTimeout = opts.scheduleReadyTimeout || ((fn, delay) => setTimeout(fn, delay))
  const clearReadyTimeout = opts.clearReadyTimeout || (handle => clearTimeout(handle))
  const now = opts.now || (() => Date.now())
  const readyTimeoutMs = Number.isFinite(opts.readyTimeoutMs) ? opts.readyTimeoutMs : DEFAULT_READY_TIMEOUT_MS

  let child = null
  let stopped = true
  let restartTimer = null
  let readyTimer = null
  let backoffMs = 0
  let state = {
    running: false,
    port: null,
    pid: null,
    restarts: 0,
    startedAt: null,
    lastError: null,
    binSource: null
  }

  function status() {
    return { ...state }
  }

  function clearPendingReadyTimer() {
    if (readyTimer) {
      clearReadyTimeout(readyTimer)
      readyTimer = null
    }
  }

  /** Parse `chunkStr` line-by-line for the ready announcement (buffered across chunks). */
  function makeReadyScanner(onReady) {
    let buf = ''
    let announced = false
    return chunkStr => {
      if (announced) return
      buf += chunkStr
      let nl
      while ((nl = buf.indexOf('\n')) !== -1) {
        const line = buf.slice(0, nl)
        buf = buf.slice(nl + 1)
        const match = line.match(READY_LINE_RE)
        if (match) {
          announced = true
          onReady(parseInt(match[1], 10))
          return
        }
      }
    }
  }

  function spawnOnce() {
    if (stopped) return

    const resolved = resolveBin()
    if (!resolved) {
      state = { ...state, running: false, port: null, pid: null, lastError: 'simplicio binary not found' }
      return
    }

    // .cmd/.bat shims must be routed through cmd.exe -- same EINVAL mitigation
    // as mcp-daemon.cjs; real .exe binaries pass through unchanged.
    // NOTE: the CLI subcommand is `web-dashboard` (or `web-ui`), not
    // `dashboard` -- `dashboard` routes to an unrelated agent-workflow TUI
    // (`agent_visualizer::dashboard_main`, src/commands/mod.rs:2126); the
    // `/api/summary` HTTP server + SIMPLICIO_DASHBOARD_READY announcement
    // this daemon depends on live under `web-dashboard` (src/commands/mod.rs
    // "web-dashboard" | "web-ui" => dashboard_command::dashboard_command).
    const invocation = buildSpawnInvocation(resolved.bin, ['web-dashboard', 'start', '--port', '0', '--no-open', '--json'])

    let spawned
    try {
      spawned = spawnFn(invocation.command, invocation.args, {
        windowsHide: true,
        windowsVerbatimArguments: invocation.windowsVerbatimArguments,
        // Mirrors mcp-daemon.cjs: stdin MUST be an open pipe held for the
        // child's whole life. We never write to it and never call
        // child.stdin.end() while supervising; only stop() ends it.
        stdio: ['pipe', 'pipe', 'pipe']
      })
    } catch (error) {
      state = { ...state, running: false, port: null, pid: null, lastError: error.message, binSource: resolved.source }
      scheduleNextRestart()
      return
    }

    child = spawned
    const startedAtMs = now()
    state = {
      // Not proven ready until the port-announcement line arrives.
      running: false,
      port: null,
      pid: Number.isInteger(spawned.pid) ? spawned.pid : null,
      restarts: state.restarts,
      startedAt: new Date(startedAtMs).toISOString(),
      lastError: null,
      binSource: resolved.source
    }

    let settled = false

    const scanForReady = makeReadyScanner(port => {
      clearPendingReadyTimer()
      state = { ...state, running: true, port, lastError: null }
    })

    if (spawned.stdout) {
      spawned.stdout.on('data', chunk => {
        const text = chunk.toString()
        log(text)
        scanForReady(text)
      })
    }
    if (spawned.stderr) spawned.stderr.on('data', chunk => log(chunk.toString()))
    if (spawned.stdin) {
      // Hold the pipe open, but never let a late EPIPE (child died first)
      // become an uncaught 'error' that takes down the Electron main process.
      spawned.stdin.on('error', () => {})
    }

    readyTimer = scheduleReadyTimeout(() => {
      readyTimer = null
      if (settled || state.running) return
      state = { ...state, lastError: 'dashboard did not announce a port' }
    }, readyTimeoutMs)

    // Node emits 'error' (spawn failure) and/or 'exit' for the same failed
    // child; guard so a single crash counts as exactly one restart.
    spawned.once('error', error => {
      if (settled) return
      settled = true
      clearPendingReadyTimer()
      state = { ...state, running: false, port: null, lastError: error.message }
      handleExit(startedAtMs)
    })

    spawned.once('exit', (code, signal) => {
      if (settled) return
      settled = true
      clearPendingReadyTimer()
      // An intentional stop() force-kills the process (tree-kill on Windows,
      // SIGTERM elsewhere) -- the web-dashboard HTTP server has no graceful
      // stdin-EOF shutdown like the MCP stdio server, so it always exits
      // non-zero/signaled when killed. That is NOT a crash; only report
      // lastError for an exit stop() did not request.
      const lastError = stopped
        ? null
        : signal
          ? `killed (${signal})`
          : code === 0
            ? 'exited (code 0) unexpectedly'
            : `exited (code ${code})`
      state = { ...state, running: false, port: null, lastError }
      handleExit(startedAtMs)
    })
  }

  function handleExit(startedAtMs) {
    child = null
    state = { ...state, pid: null, port: null }
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
    clearPendingReadyTimer()
    if (restartTimer) {
      clearScheduled(restartTimer)
      restartTimer = null
    }

    const dying = child
    child = null
    state = { ...state, running: false, pid: null, port: null }

    if (!dying) return status()

    // Graceful first (EOF on stdin), same as mcp-daemon.cjs -- this is the
    // ONLY place stdin is ever ended, never while supervising.
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

const DEFAULT_SUMMARY_TIMEOUT_MS = 5000

/**
 * `GET http://127.0.0.1:<port>/api/summary?from=&to=&group=` -- the
 * dashboard's savings-ledger aggregation (src/dashboard_command.rs
 * summary_response / build_summary). Uses the Node-global `fetch` (Electron
 * main runs Node 22+; no axios/node-fetch dependency).
 *
 * Resolves `{ok:true, summary}` on a 2xx JSON response, or `{ok:false,
 * error}` -- never throws. `error` distinguishes an invalid port, a network
 * failure, a non-2xx status, and a timeout so callers can show an honest
 * message instead of a generic failure.
 *
 * @param {number} port - the daemon's announced port (status().port).
 * @param {object} [params]
 * @param {string|number} [params.from] - unix-seconds range start.
 * @param {string|number} [params.to] - unix-seconds range end.
 * @param {'hour'|'day'|'month'} [params.group] - aggregation bucket.
 * @param {object} [opts]
 * @param {Function} [opts.fetchFn] - fetch stand-in (tests).
 * @param {number} [opts.timeoutMs] - abort after this long (default 5000).
 */
async function fetchSummary(port, params = {}, opts = {}) {
  const fetchFn = opts.fetchFn || (typeof fetch === 'function' ? fetch : undefined)
  if (typeof fetchFn !== 'function') {
    return { ok: false, error: 'fetch is not available in this runtime' }
  }
  if (!Number.isInteger(port) || port <= 0) {
    return { ok: false, error: 'invalid dashboard port' }
  }

  const query = new URLSearchParams()
  if (params.from !== undefined && params.from !== null && params.from !== '') query.set('from', String(params.from))
  if (params.to !== undefined && params.to !== null && params.to !== '') query.set('to', String(params.to))
  if (params.group) query.set('group', String(params.group))
  const qs = query.toString()
  const url = `http://127.0.0.1:${port}/api/summary${qs ? `?${qs}` : ''}`

  const timeoutMs = Number.isFinite(opts.timeoutMs) ? opts.timeoutMs : DEFAULT_SUMMARY_TIMEOUT_MS
  const AbortControllerImpl = opts.AbortControllerImpl || AbortController
  const controller = new AbortControllerImpl()
  const timer = setTimeout(() => controller.abort(), timeoutMs)
  if (timer.unref) timer.unref()

  try {
    const response = await fetchFn(url, { signal: controller.signal })
    if (!response.ok) {
      return { ok: false, error: `dashboard summary request failed: HTTP ${response.status}` }
    }
    const summary = await response.json()
    return { ok: true, summary }
  } catch (error) {
    if (error && error.name === 'AbortError') {
      return { ok: false, error: `dashboard summary request timed out after ${timeoutMs}ms` }
    }
    return { ok: false, error: error && error.message ? error.message : String(error) }
  } finally {
    clearTimeout(timer)
  }
}

module.exports = {
  createDashboardDaemon,
  fetchSummary,
  READY_LINE_RE,
  DEFAULT_READY_TIMEOUT_MS,
  DEFAULT_SUMMARY_TIMEOUT_MS
}
