'use strict'

/**
 * simplicio-ipc.cjs
 *
 * Wires the "Simplicio Savings" surface (savings report, doctor, editor MCP
 * detection/registration, the always-on MCP stdio daemon) into the main
 * process's ipcMain, and owns the one supervised McpDaemon instance for the
 * app's lifetime. main.cjs calls registerSimplicioIpc(ipcMain, opts) once at
 * module init (registration doesn't need `app.whenReady()`), then drives the
 * returned daemon's start()/stop() from `app.whenReady()` / `before-quit`.
 */

const os = require('node:os')

const { resolveSimplicioBin, runSimplicio, parseSimplicioJsonOutput } = require('./simplicio-bin.cjs')
const { detectEditors, registerAll } = require('./editor-integrations.cjs')
const { createMcpDaemon } = require('./mcp-daemon.cjs')
const { createDashboardDaemon, fetchSummary } = require('./dashboard-daemon.cjs')
const { createCuaMcpDaemon } = require('./cua-mcp-daemon.cjs')
const { readSavingsSessions } = require('./savings-ledger.cjs')

/**
 * Run a `--json` subcommand and return `{ok:true, [resultKey]:<parsed>}` or
 * `{ok:false, error, raw?}`. Never throws.
 *
 * @param {Function} [runner] - runSimplicio stand-in (tests).
 * @param {object} [runOpts] - forwarded to the runner (e.g. {cwd}).
 */
async function runJsonCommand(args, label, resultKey, runner = runSimplicio, runOpts = undefined) {
  const result = await runner(args, runOpts)

  if (!result.stdout && !result.ok) {
    return { ok: false, error: result.stderr || `${label} failed` }
  }

  const parsed = parseSimplicioJsonOutput(result.stdout)
  if (parsed === null) {
    return { ok: false, error: `could not parse ${label} output`, raw: result.stdout }
  }

  return { ok: true, [resultKey]: parsed }
}

/**
 * `simplicio savings report --json`. Resolves `{ok:true, report}` on
 * success -- the `report` field name matches the
 * `SimplicioSavingsBridge`/`SavingsReportResult` contract documented in
 * `src/app/savings/types.ts` (a parallel in-flight change consuming this
 * bridge), so the renderer's `parseSavingsReport(result.report)` sees the
 * shape it expects without another round of wiring.
 *
 * Spawned with cwd = os.homedir(): the runtime discovers `.simplicio/ledger`
 * relative to its cwd, and the Electron process's own cwd has no ledger --
 * without this the report says "no savings" while the Sessions section
 * (which reads the home ledger directly) shows events.
 *
 * @param {Function} [runner] - runSimplicio stand-in (tests).
 */
function savingsReport(runner) {
  return runJsonCommand(['savings', 'report', '--json'], 'simplicio savings report', 'report', runner, {
    cwd: os.homedir()
  })
}

/**
 * `simplicio doctor --json`. Resolves `{ok:true, doctor}` on success -- the
 * `doctor` field name matches the local `DoctorRunResult` contract declared
 * in `src/components/onboarding/doctor-step.tsx` (a parallel in-flight
 * change consuming this bridge via `mapDoctorToChecklist(result.doctor)`).
 *
 * @param {Function} [runner] - runSimplicio stand-in (tests).
 */
function doctorRun(runner) {
  return runJsonCommand(['doctor', '--json'], 'simplicio doctor', 'doctor', runner)
}

/**
 * `simplicio memory status --json` (schema `simplicio.memory-backend/v1`:
 * selected backend, database path, memory_items counts, guardian roster).
 * Resolves `{ok:true, memory}` on success.
 *
 * @param {Function} [runner] - runSimplicio stand-in (tests).
 */
function memoryStatus(runner) {
  return runJsonCommand(['memory', 'status', '--json'], 'simplicio memory status', 'memory', runner)
}

/**
 * Register every IPC handler for the Simplicio Savings surface and start (but
 * do not yet spawn) the supervised MCP daemon.
 *
 * @param {import('electron').IpcMain} ipcMain
 * @param {object} [opts]
 * @param {ReturnType<typeof createMcpDaemon>} [opts.daemon] - injected MCP daemon (tests).
 * @param {ReturnType<typeof createDashboardDaemon>} [opts.dashboardDaemon] - injected dashboard daemon (tests).
 * @param {ReturnType<typeof createCuaMcpDaemon>} [opts.cuaMcpDaemon] - injected cua-mcp daemon (tests).
 * @param {Function} [opts.resolveCuaMcpCommand] - () => {command, args, env} for the
 *   cua-mcp daemon's Python child (`python -m hermes_cli.main mcp serve`).
 *   main.cjs supplies its real python/venv/env resolver here (mirroring its
 *   own backend-spawn resolution) so this module never duplicates that logic;
 *   left undefined the daemon still starts but reports an honest lastError
 *   instead of spawning (see cua-mcp-daemon.cjs).
 * @returns {ReturnType<typeof createMcpDaemon>} the MCP daemon instance -- callers
 *   drive its lifecycle with daemon.start() on app ready and daemon.stop() on
 *   before-quit. The dashboard daemon and the cua-mcp daemon are returned
 *   separately as `.dashboardDaemon` / `.cuaMcpDaemon` on the same object so
 *   main.cjs can drive all three from one registerSimplicioIpc() call without
 *   extra wiring points.
 */
function registerSimplicioIpc(ipcMain, opts = {}) {
  const daemon = opts.daemon || createMcpDaemon({ log: opts.log })
  const dashboardDaemon = opts.dashboardDaemon || createDashboardDaemon({ log: opts.log })
  const cuaMcpDaemon = opts.cuaMcpDaemon || createCuaMcpDaemon({ log: opts.log, resolveCommand: opts.resolveCuaMcpCommand })

  ipcMain.handle('simplicio:savings-report', () => savingsReport())
  ipcMain.handle('simplicio:doctor', () => doctorRun())
  ipcMain.handle('simplicio:editors-detect', () => {
    try {
      return { ok: true, editors: detectEditors() }
    } catch (error) {
      return { ok: false, editors: [], error: error.message }
    }
  })
  ipcMain.handle('simplicio:mcp-register', () => registerAll())
  ipcMain.handle('simplicio:mcp-daemon-status', () => daemon.status())
  ipcMain.handle('simplicio:mcp-daemon-start', () => daemon.start())
  ipcMain.handle('simplicio:mcp-daemon-stop', () => daemon.stop())
  ipcMain.handle('simplicio:memory-status', () => memoryStatus())
  // Direct ledger read -- no spawn, no LLM. `request` may carry an optional
  // repoPath whose per-repo ledger is merged (deduped by event_id) with the
  // home ledger.
  ipcMain.handle('simplicio:savings-sessions', (_event, request) =>
    readSavingsSessions({ repoPath: request && request.repoPath })
  )

  // Supervised `simplicio dashboard start` daemon (electron/dashboard-daemon.cjs):
  // status/start/stop mirror the MCP daemon handlers above, plus a summary
  // fetch that resolves against the daemon's own announced port (never a
  // renderer-supplied port -- the renderer only ever asks "what does MY
  // daemon report").
  ipcMain.handle('simplicio:dashboard-status', () => dashboardDaemon.status())
  ipcMain.handle('simplicio:dashboard-start', () => dashboardDaemon.start())
  ipcMain.handle('simplicio:dashboard-stop', () => dashboardDaemon.stop())
  ipcMain.handle('simplicio:dashboard-summary', (_event, request) => {
    const current = dashboardDaemon.status()
    if (!current.running || !current.port) {
      return Promise.resolve({ ok: false, error: 'dashboard daemon not running' })
    }
    return fetchSummary(current.port, request || {})
  })

  // Supervised `python -m hermes_cli.main mcp serve` daemon
  // (electron/cua-mcp-daemon.cjs) -- exposes the computer-use toolset over
  // MCP stdio. Same status/start/stop bridge shape as the daemons above.
  ipcMain.handle('simplicio:cua-mcp-status', () => cuaMcpDaemon.status())
  ipcMain.handle('simplicio:cua-mcp-start', () => cuaMcpDaemon.start())
  ipcMain.handle('simplicio:cua-mcp-stop', () => cuaMcpDaemon.stop())

  daemon.dashboardDaemon = dashboardDaemon
  daemon.cuaMcpDaemon = cuaMcpDaemon
  return daemon
}

module.exports = {
  registerSimplicioIpc,
  savingsReport,
  doctorRun,
  memoryStatus,
  resolveSimplicioBin
}
