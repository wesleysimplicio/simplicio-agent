'use strict'

/**
 * simplicio-bin.cjs
 *
 * Resolves the `simplicio` runtime binary (the Rust kernel) and runs it as a
 * child process. This is the single place that decides which binary the
 * desktop invokes for the "Simplicio Savings" surface (savings report,
 * doctor, MCP registration, the MCP stdio daemon) — every caller goes
 * through resolveSimplicioBin()/runSimplicio() instead of hardcoding a path.
 *
 * Kept electron-free (no `require('electron')`) so it can be unit-tested with
 * `node --test`, same pattern as backend-probes.cjs / desktop-uninstall.cjs.
 * Every resolved path is verified with fs before use — never an invented
 * path; resolveSimplicioBin() returns null when nothing checks out.
 */

const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')
const { execFileSync, spawn } = require('node:child_process')

const IS_WINDOWS = process.platform === 'win32'

// Windows resolves a bare command name from PATH by trying each PATHEXT
// extension in turn (mirrors cmd.exe / `where`). POSIX has no such notion —
// an executable named exactly `simplicio` is what PATH lookup expects there.
const WINDOWS_EXTENSIONS = ['.exe', '.cmd', '.bat', '.com']

/** True iff `filePath` exists and is a regular file. Never throws. */
function isExecutableFile(filePath) {
  if (!filePath) return false
  try {
    return fs.statSync(filePath).isFile()
  } catch {
    return false
  }
}

/**
 * Search PATH for a `simplicio` executable, Windows-PATHEXT aware. Returns
 * the absolute path, or null. Pure function of `pathEnv`/`isWindows`/`exists`
 * so it is unit-testable without touching the real filesystem or PATH.
 *
 * Windows search is TWO passes across ALL dirs: real native binaries
 * (.exe/.com) first, script shims (.cmd/.bat) only when no .exe exists
 * anywhere on PATH. Node can spawn an .exe directly, but spawning a .cmd/.bat
 * without a shell raises EINVAL (CVE-2024-27980 mitigation) and needs a
 * cmd.exe wrapper — so a real binary always beats a wrapper, even one that
 * appears earlier on PATH.
 */
const WINDOWS_NATIVE_EXTENSIONS = ['.exe', '.com']
const WINDOWS_SCRIPT_EXTENSIONS = ['.cmd', '.bat']

function findSimplicioOnPath(pathEnv, isWindows = IS_WINDOWS, exists = isExecutableFile) {
  const dirs = String(pathEnv || '')
    .split(path.delimiter)
    .filter(Boolean)
  const passes = isWindows
    ? [WINDOWS_NATIVE_EXTENSIONS.map(ext => `simplicio${ext}`), WINDOWS_SCRIPT_EXTENSIONS.map(ext => `simplicio${ext}`)]
    : [['simplicio']]
  for (const names of passes) {
    for (const dir of dirs) {
      for (const name of names) {
        const candidate = path.join(dir, name)
        if (exists(candidate)) return candidate
      }
    }
  }
  return null
}

const PROBE_TIMEOUT_MS = 8000

// bin path -> boolean. A probe result is stable for the process lifetime
// (the daemon re-resolves on every restart; without a cache each crash-loop
// tick would shell out an extra --help).
const probeCache = new Map()

/**
 * The identity marker a real runtime's `--help` must carry. The desktop's
 * Savings surface needs the Rust kernel specifically — its help text lists
 * the `savings report` / `savings record` command family. Both observed
 * impostors fail this: a broken pip launcher stub exits 1 before printing
 * anything, and the `~/.local/bin/simplicio.cmd` Hermes-agent shim prints a
 * `usage: hermes …` help with no savings commands at all.
 */
const RUNTIME_HELP_MARKER = /\bsavings\b/i

/**
 * True iff `<bin> --help` exits 0 within the timeout AND its output
 * identifies the simplicio RUNTIME (not just any executable named
 * simplicio). This is the honest "does this candidate actually work" gate
 * (same pattern as backend-probes.cjs's verifyHermesCli), needed because
 * existence checks pass for two real-world impostors on this machine — see
 * RUNTIME_HELP_MARKER above. Routed through buildSpawnInvocation so probing
 * a .cmd shim doesn't itself EINVAL.
 *
 * `opts.execFileSyncFn` is injectable for tests.
 */
function probeSimplicioBin(bin, opts = {}) {
  if (probeCache.has(bin)) return probeCache.get(bin)
  const execFileSyncFn = opts.execFileSyncFn || execFileSync
  const invocation = buildSpawnInvocation(bin, ['--help'], opts)
  let ok = false
  try {
    const stdout = execFileSyncFn(invocation.command, invocation.args, {
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'ignore'],
      timeout: PROBE_TIMEOUT_MS,
      windowsHide: true,
      windowsVerbatimArguments: invocation.windowsVerbatimArguments
    })
    ok = RUNTIME_HELP_MARKER.test(String(stdout || ''))
  } catch {
    ok = false
  }
  probeCache.set(bin, ok)
  return ok
}

/**
 * Resolve the `simplicio` binary the desktop should invoke, in priority
 * order:
 *   1. `SIMPLICIO_BIN` env override (wins whenever set AND it exists on disk)
 *   2. `simplicio` resolved from PATH (.exe preferred over .cmd/.bat shims)
 *   3. the dev-checkout build, `<home>/m/ai/simplicio/simplicio.exe`
 *   4. `~/.local/bin/simplicio.cmd` (the documented Windows install location)
 *
 * The dev .exe outranks the local-bin .cmd deliberately: a real native
 * binary spawns directly, while a .cmd shim needs the cmd.exe wrapper (see
 * buildSpawnInvocation) — prefer the .exe whenever one is available.
 *
 * Every candidate must (a) exist on disk AND (b) pass a live `--help` probe
 * before being returned — existence alone is not proof it runs (a broken
 * pip launcher stub on PATH exists but exits 1 on everything). A candidate
 * that fails the probe is skipped and the next rung is tried. Returns
 * `{ bin, source }` or `null` when nothing resolves — callers must treat a
 * null result as "not installed", never fabricate a path.
 *
 * `opts.env`/`opts.platform`/`opts.homedir`/`opts.exists`/`opts.devRoot`/
 * `opts.verify` are injectable for tests. When a custom `exists` is injected
 * (pure unit tests with fake paths), the live probe defaults OFF — probing a
 * path that doesn't really exist would always fail; tests that exercise the
 * probe behavior inject `verify` explicitly.
 */
function resolveSimplicioBin(opts = {}) {
  const env = opts.env || process.env
  const isWindows = opts.platform ? opts.platform === 'win32' : IS_WINDOWS
  const homedir = opts.homedir || os.homedir()
  const exists = opts.exists || isExecutableFile
  const verify = opts.verify || (opts.exists ? () => true : bin => probeSimplicioBin(bin, opts))

  const usable = bin => exists(bin) && verify(bin)

  const override = env.SIMPLICIO_BIN
  if (override && usable(override)) {
    return { bin: override, source: 'env:SIMPLICIO_BIN' }
  }

  const pathEnv = env.PATH || env.Path || env.path || ''
  const onPath = findSimplicioOnPath(pathEnv, isWindows, bin => usable(bin))
  if (onPath) {
    return { bin: onPath, source: 'path' }
  }

  const devRoot = opts.devRoot || path.join(homedir, 'm', 'ai')
  const devBin = path.join(devRoot, 'simplicio', 'simplicio.exe')
  if (usable(devBin)) {
    return { bin: devBin, source: 'dev-fallback' }
  }

  const localBin = path.join(homedir, '.local', 'bin', 'simplicio.cmd')
  if (usable(localBin)) {
    return { bin: localBin, source: 'local-bin' }
  }

  return null
}

/** True when `bin` is a .cmd/.bat shim that Node cannot spawn directly. */
function isCmdShim(bin) {
  return /\.(cmd|bat)$/i.test(String(bin || ''))
}

/**
 * Build the actual spawn() invocation for a resolved binary + fixed argv.
 *
 * Node on Windows refuses to spawn .cmd/.bat files without a shell (EINVAL,
 * the CVE-2024-27980 mitigation), so shims are wrapped as
 * `cmd.exe /d /s /c "<quoted command line>"` with windowsVerbatimArguments
 * (we do the quoting ourselves; cmd.exe would misparse Node's re-quoting).
 * This is NOT `shell:true` with interpolated input — the argv here is always
 * a fixed, code-controlled array; each token is quoted individually and
 * cmd metacharacters are never interpreted out of user data.
 *
 * Returns `{ command, args, windowsVerbatimArguments }`.
 */
function buildSpawnInvocation(bin, args, opts = {}) {
  const argv = Array.isArray(args) ? args : []
  const isWindows = opts.platform ? opts.platform === 'win32' : IS_WINDOWS
  if (!isWindows || !isCmdShim(bin)) {
    return { command: bin, args: argv, windowsVerbatimArguments: false }
  }

  // Quote each token that needs it (spaces/quotes); our fixed flags never do,
  // but the shim path itself may live under a dir with spaces.
  const quote = token => {
    const s = String(token)
    return /[\s"^&|<>()%!]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
  }
  const commandLine = [bin, ...argv].map(quote).join(' ')
  const comspec = (opts.env || process.env).comspec || 'cmd.exe'
  return {
    command: comspec,
    // /d: skip AutoRun, /s: preserve the outer quotes exactly, /c: run + exit.
    args: ['/d', '/s', '/c', `"${commandLine}"`],
    windowsVerbatimArguments: true
  }
}

const DEFAULT_RUN_TIMEOUT_MS = 30000

/**
 * Run the simplicio binary with `args` (always an array — never shell
 * interpolation of untrusted input) and capture stdout/stderr.
 *
 * Resolves with `{ ok, stdout, stderr, code }`. `ok` is true only for a
 * clean zero exit; a non-zero exit, a spawn failure, or an unresolved binary
 * all resolve (never reject) with `ok:false` and an explanatory `stderr`, so
 * callers never need a try/catch around this.
 *
 * @param {string[]} args
 * @param {object} [opts]
 * @param {number} [opts.timeoutMs] - Kill the child after this long (default 30s).
 * @param {{bin:string, source:string}} [opts.resolved] - Skip resolution and
 *   use this pre-resolved binary (tests / callers that already resolved once).
 */
function runSimplicio(args, opts = {}) {
  const argv = Array.isArray(args) ? args : []
  const resolved = opts.resolved || resolveSimplicioBin(opts)

  if (!resolved) {
    return Promise.resolve({
      ok: false,
      stdout: '',
      stderr: 'simplicio binary not found',
      code: null
    })
  }

  const timeoutMs = Number.isFinite(opts.timeoutMs) ? opts.timeoutMs : DEFAULT_RUN_TIMEOUT_MS
  const spawnFn = opts.spawnFn || spawn
  // .cmd/.bat shims are routed through cmd.exe (Windows EINVAL mitigation);
  // real binaries spawn directly. See buildSpawnInvocation.
  const invocation = buildSpawnInvocation(resolved.bin, argv, opts)

  return new Promise(resolve => {
    let stdout = ''
    let stderr = ''
    let settled = false
    let child

    try {
      child = spawnFn(invocation.command, invocation.args, {
        windowsHide: true,
        windowsVerbatimArguments: invocation.windowsVerbatimArguments,
        stdio: ['ignore', 'pipe', 'pipe']
      })
    } catch (error) {
      resolve({ ok: false, stdout: '', stderr: error.message, code: null })
      return
    }

    const timer = setTimeout(() => {
      if (settled) return
      try {
        child.kill()
      } catch {
        // best effort
      }
    }, timeoutMs)
    if (timer.unref) timer.unref()

    if (child.stdout) child.stdout.on('data', chunk => (stdout += chunk.toString()))
    if (child.stderr) child.stderr.on('data', chunk => (stderr += chunk.toString()))

    child.once('error', error => {
      if (settled) return
      settled = true
      clearTimeout(timer)
      resolve({ ok: false, stdout, stderr: stderr || error.message, code: null })
    })

    child.once('exit', (code, signal) => {
      if (settled) return
      settled = true
      clearTimeout(timer)
      resolve({
        ok: code === 0,
        stdout,
        stderr: signal ? `${stderr}\nkilled (${signal})`.trim() : stderr,
        code
      })
    })
  })
}

/**
 * Tolerantly parse a `--json` command's stdout, which may be preceded (or
 * interleaved, for a streamed command) by JSONL progress events shaped like
 * `{"schema":"simplicio.progress/v1",...}`. Strategy:
 *   1. Drop every standalone line that parses as JSON with that progress
 *      schema.
 *   2. Parse whatever remains (a single JSON line, or a pretty-printed
 *      multi-line JSON object/array) as one blob.
 *   3. If that fails, fall back to the last individual line that parses as
 *      JSON on its own.
 * Returns the parsed value, or null if nothing in stdout is valid JSON.
 */
function parseSimplicioJsonOutput(stdout) {
  const text = String(stdout || '')
  if (!text.trim()) return null

  const lines = text.split(/\r?\n/)
  const kept = lines.filter(line => {
    const trimmed = line.trim()
    if (!trimmed) return false
    try {
      const parsed = JSON.parse(trimmed)
      if (parsed && typeof parsed === 'object' && parsed.schema === 'simplicio.progress/v1') {
        return false
      }
    } catch {
      // Not a standalone JSON line — likely part of a multi-line object; keep it.
    }
    return true
  })

  const candidate = kept.join('\n').trim()
  if (candidate) {
    try {
      return JSON.parse(candidate)
    } catch {
      // fall through to the per-line fallback below
    }
  }

  for (let i = lines.length - 1; i >= 0; i--) {
    const trimmed = lines[i].trim()
    if (!trimmed) continue
    try {
      return JSON.parse(trimmed)
    } catch {
      continue
    }
  }

  return null
}

module.exports = {
  resolveSimplicioBin,
  runSimplicio,
  findSimplicioOnPath,
  isExecutableFile,
  isCmdShim,
  buildSpawnInvocation,
  probeSimplicioBin,
  parseSimplicioJsonOutput,
  WINDOWS_EXTENSIONS,
  WINDOWS_NATIVE_EXTENSIONS,
  WINDOWS_SCRIPT_EXTENSIONS,
  DEFAULT_RUN_TIMEOUT_MS,
  PROBE_TIMEOUT_MS
}
