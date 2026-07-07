'use strict'

/**
 * simplicio-ipc.cjs
 *
 * Wires the "Simplicio Savings" surface (savings report, doctor, editor MCP
 * detection/registration, the always-on MCP stdio daemon) into the main
 * process's ipcMain, and owns the one supervised McpDaemon instance for the
 * app's lifetime. main.cjs calls registerSimplicioIpc(ipcMain) once at
 * module init (registration doesn't need `app.whenReady()`), then drives the
 * returned daemon's start()/stop() from `app.whenReady()` / `before-quit`.
 */

const { resolveSimplicioBin, runSimplicio, parseSimplicioJsonOutput } = require('./simplicio-bin.cjs')
const { detectEditors, registerAll } = require('./editor-integrations.cjs')
const { createMcpDaemon } = require('./mcp-daemon.cjs')
const { readSavingsSessions } = require('./savings-ledger.cjs')

/**
 * Run a `--json` subcommand and return `{ok:true, [resultKey]:<parsed>}` or
 * `{ok:false, error, raw?}`. Never throws.
 *
 * @param {Function} [runner] - runSimplicio stand-in (tests).
 */
async function runJsonCommand(args, label, resultKey, runner = runSimplicio) {
  const result = await runner(args)

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
 * @param {Function} [runner] - runSimplicio stand-in (tests).
 */
function savingsReport(runner) {
  return runJsonCommand(['savings', 'report', '--json'], 'simplicio savings report', 'report', runner)
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
 * Register every IPC handler for the Simplicio Savings surface and start (but
 * do not yet spawn) the supervised MCP daemon.
 *
 * @param {import('electron').IpcMain} ipcMain
 * @param {object} [opts]
 * @param {ReturnType<typeof createMcpDaemon>} [opts.daemon] - injected daemon (tests).
 * @returns {ReturnType<typeof createMcpDaemon>} the daemon instance -- callers
 *   drive its lifecycle with daemon.start() on app ready and daemon.stop() on
 *   before-quit.
 */
function registerSimplicioIpc(ipcMain, opts = {}) {
  const daemon = opts.daemon || createMcpDaemon({ log: opts.log })

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

  return daemon
}

module.exports = {
  registerSimplicioIpc,
  savingsReport,
  doctorRun,
  resolveSimplicioBin
}
