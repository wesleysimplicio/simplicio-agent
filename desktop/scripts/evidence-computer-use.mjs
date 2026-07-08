// Evidence harness: proves the `computer_use` tool (cua-driver backed) can
// actually drive Windows 11 end to end -- screenshot, click, and type --
// through the same surface the product uses (tools/computer_use/tool.py's
// `handle_computer_use`), not a mock.
//
// Modeled on evidence-e2e.mjs's "honest by construction" contract: every
// step gets an explicit pass/fail verdict (never silently skipped), a
// screenshot is saved per step when one is available, and a run.json
// manifest lands in the evidence dir regardless of outcome. A step that
// cannot be reached is recorded as FAIL with the reason, never omitted.
//
// IMPORTANT: this harness does NOT install cua-driver. On a box where the
// driver isn't installed, step 1 ("driver-present") fails honestly with the
// install hint -- that is the CORRECT result there, not a bug in the
// harness. Never fake a pass.
//
// Ownership note: this file is the single artifact this change owns. It is
// intentionally self-contained -- including its Python driver, inlined as a
// template literal near the bottom -- so it has zero dependency on Electron
// or Python files that may be changing concurrently elsewhere in the repo.
//
// Usage:
//   node scripts/evidence-computer-use.mjs [--out <dir>] [--app <name>]
//
// Exit code: 0 iff every REQUIRED step passed; 1 if any required step
// failed (or never ran); 2 on a harness-level crash (mirrors evidence-e2e.mjs).

import { spawn, spawnSync } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const IS_WINDOWS = process.platform === 'win32'

const DESKTOP_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
// The repo this script itself lives in -- evidence always lands here,
// mirroring evidence-e2e.mjs's own DESKTOP_ROOT/'..' convention.
const SOURCE_REPO_ROOT = path.resolve(DESKTOP_ROOT, '..')

const args = process.argv.slice(2)
function argVal(flag) {
  const i = args.indexOf(flag)
  return i >= 0 ? args[i + 1] : null
}

const outDir = path.resolve(
  argVal('--out') || path.join(SOURCE_REPO_ROOT, '.orchestrator', 'evidence', 'desktop-computer-use')
)
const targetApp = argVal('--app') || 'Notepad'

// ---------------------------------------------------------------------------
// Filesystem helpers
// ---------------------------------------------------------------------------

function fileExists(p) {
  try {
    return fs.statSync(p).isFile()
  } catch {
    return false
  }
}

function directoryExists(p) {
  try {
    return fs.statSync(p).isDirectory()
  } catch {
    return false
  }
}

// Same check desktop/electron/main.cjs uses (isHermesSourceRoot): a real
// Hermes/Simplicio Python checkout has hermes_cli/main.py at its root.
function isHermesSourceRoot(root) {
  return directoryExists(root) && fileExists(path.join(root, 'hermes_cli', 'main.py'))
}

// The effective Python/CLI root: honour HERMES_DESKTOP_HERMES_ROOT (the same
// override evidence-e2e.mjs sets for Electron, and that
// desktop/electron/main.cjs's resolveHermesBackend() reads first) when it
// points at a real checkout; otherwise fall back to this script's own repo.
function resolveHermesRoot() {
  const override = process.env.HERMES_DESKTOP_HERMES_ROOT
  if (override) {
    const resolved = path.resolve(override)
    if (isHermesSourceRoot(resolved)) return resolved
  }
  return SOURCE_REPO_ROOT
}

const HERMES_ROOT = resolveHermesRoot()

// ---------------------------------------------------------------------------
// PATH / interpreter resolution
//
// Mirrors findOnPath() / findPythonForRoot() / getVenvPython() in
// desktop/electron/main.cjs -- env override wins, then the repo-root venv
// (.venv before venv, Scripts/ on Windows), then PATH. Never a hardcoded
// absolute path. This is a deliberately smaller version of main.cjs's
// findSystemPython(): it skips the Windows registry / MS-Store-stub /
// py-launcher version-pinning passes (main.cjs needs those to avoid
// bricking a GUI first-run install; this harness only needs "find *a*
// working interpreter" and the repo venv is the expected common case).
// ---------------------------------------------------------------------------

function findOnPath(command) {
  if (!command) return null
  if (path.isAbsolute(command) || command.includes('/') || command.includes('\\')) {
    return fileExists(command) ? command : null
  }
  const pathEntries = String(process.env.PATH || process.env.Path || '')
    .split(path.delimiter)
    .filter(Boolean)
  // PATHEXT extensions before the bare name (Windows command-resolution
  // semantics) -- see the historical bug this fixes in
  // desktop/electron/windows-hermes-resolution.test.cjs.
  const extensions = IS_WINDOWS
    ? [...(process.env.PATHEXT || '.COM;.EXE;.BAT;.CMD').split(';').filter(Boolean), '']
    : ['']
  for (const dir of pathEntries) {
    for (const ext of extensions) {
      const candidate = path.join(dir, `${command}${ext}`)
      if (fileExists(candidate)) return candidate
    }
  }
  return null
}

function resolvePython(root) {
  const override = process.env.HERMES_DESKTOP_PYTHON
  if (override && fileExists(override)) {
    return { python: override, source: 'env:HERMES_DESKTOP_PYTHON' }
  }

  const relative = IS_WINDOWS
    ? [
        ['.venv', 'Scripts', 'python.exe'],
        ['venv', 'Scripts', 'python.exe']
      ]
    : [
        ['.venv', 'bin', 'python'],
        ['venv', 'bin', 'python']
      ]
  for (const parts of relative) {
    const candidate = path.join(root, ...parts)
    if (fileExists(candidate)) return { python: candidate, source: `venv:${parts.join('/')}` }
  }

  for (const cmd of IS_WINDOWS ? ['python.exe', 'py.exe'] : ['python3', 'python']) {
    const found = findOnPath(cmd)
    if (found) return { python: found, source: `path:${cmd}` }
  }
  return null
}

// Mirrors buildDesktopBackendEnv()'s PYTHONPATH assembly in
// desktop/electron/backend-env.cjs: put the resolved root on PYTHONPATH so
// `import hermes_cli` / `import tools` resolve from source, same as the
// desktop-managed backend does. Also prepends the interpreter's own
// Scripts/bin dir to PATH so console-script shims resolve the same way.
function buildPythonEnv(pythonInfo, root) {
  const delimiter = path.delimiter
  const currentPythonPath = process.env.PYTHONPATH || ''
  const pythonPath = [root, currentPythonPath].filter(Boolean).join(delimiter)

  const scriptsDir = path.dirname(pythonInfo.python)
  const currentPath = process.env.PATH || process.env.Path || ''
  const mergedPath = [scriptsDir, currentPath].filter(Boolean).join(delimiter)

  return { ...process.env, PYTHONPATH: pythonPath, PATH: mergedPath }
}

// ---------------------------------------------------------------------------
// Manifest / step bookkeeping
// ---------------------------------------------------------------------------

const REQUIRED_STEPS = new Set([
  'driver-present',
  'python-resolved',
  'doctor',
  'notepad-launch',
  'cu-capture-before',
  'cu-type-sentinel',
  'cu-capture-after',
  'cu-sentinel-verified'
])

const manifest = {
  started_at: new Date().toISOString(),
  platform: process.platform,
  source_repo_root: SOURCE_REPO_ROOT,
  hermes_root: HERMES_ROOT,
  target_app: targetApp,
  steps: []
}

let stepSeq = 0

function record(name, status, detail, extra = {}) {
  const rec = {
    n: ++stepSeq,
    name,
    status, // 'pass' | 'fail'
    detail: detail || '',
    required: REQUIRED_STEPS.has(name),
    ...extra
  }
  manifest.steps.push(rec)
  console.log(`${status === 'pass' ? 'PASS' : 'FAIL'} ${rec.n} ${name}${rec.detail ? ': ' + rec.detail : ''}`)
  return rec
}

function findStep(name) {
  return manifest.steps.find(s => s.name === name) || null
}

function truncate(str, n) {
  const s = String(str || '')
  return s.length > n ? s.slice(0, n) + '…' : s
}

function saveScreenshotForStep(rec, imageB64) {
  try {
    const file = path.join(outDir, `${String(rec.n).padStart(2, '0')}-${rec.name}.png`)
    fs.writeFileSync(file, Buffer.from(imageB64, 'base64'))
    return file
  } catch (err) {
    console.log(`  (failed to save screenshot for ${rec.name}: ${err.message})`)
    return null
  }
}

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms))
}

function parseTrailingJson(stdout) {
  const lines = String(stdout || '').split(/\r?\n/)
  for (let i = lines.length - 1; i >= 0; i--) {
    const trimmed = lines[i].trim()
    if (!trimmed) continue
    try {
      return JSON.parse(trimmed)
    } catch {
      // Not JSON on its own (stray log line) -- keep scanning backward.
    }
  }
  return null
}

// ---------------------------------------------------------------------------
// Step 1: driver-present
// ---------------------------------------------------------------------------

function stepDriverPresent() {
  const driverCmdName = (process.env.HERMES_CUA_DRIVER_CMD || '').trim() || 'cua-driver'
  const resolved = findOnPath(driverCmdName)
  if (!resolved) {
    record(
      'driver-present',
      'fail',
      `'${driverCmdName}' not found (checked $HERMES_CUA_DRIVER_CMD and PATH). ` +
        'This harness does not install it -- run `hermes computer-use install` first.',
      { driver_cmd: driverCmdName }
    )
    return null
  }
  record('driver-present', 'pass', `${driverCmdName} -> ${resolved}`, {
    driver_cmd: driverCmdName,
    driver_bin: resolved
  })
  return resolved
}

// ---------------------------------------------------------------------------
// Interpreter resolution step (feeds the doctor + drive steps)
// ---------------------------------------------------------------------------

function stepPythonResolved() {
  const info = resolvePython(HERMES_ROOT)
  if (!info) {
    record(
      'python-resolved',
      'fail',
      'no python interpreter found (checked $HERMES_DESKTOP_PYTHON, ' +
        `${path.join(HERMES_ROOT, '.venv')}, ${path.join(HERMES_ROOT, 'venv')}, and PATH)`
    )
    return null
  }
  record('python-resolved', 'pass', `${info.python} (${info.source})`)
  return info
}

// ---------------------------------------------------------------------------
// Step 2: doctor
// ---------------------------------------------------------------------------

function stepDoctor(pythonInfo) {
  if (!pythonInfo) {
    record('doctor', 'fail', 'no python interpreter resolved; see python-resolved step')
    return null
  }

  const cliArgs = ['-m', 'hermes_cli.main', 'computer-use', 'doctor', '--json']
  const result = spawnSync(pythonInfo.python, cliArgs, {
    cwd: HERMES_ROOT,
    env: buildPythonEnv(pythonInfo, HERMES_ROOT),
    encoding: 'utf8',
    timeout: 30_000,
    maxBuffer: 16 * 1024 * 1024,
    windowsHide: true
  })

  if (result.error) {
    record('doctor', 'fail', `spawn failed: ${result.error.message}`, {
      command: [pythonInfo.python, ...cliArgs]
    })
    return null
  }

  const stdout = (result.stdout || '').trim()
  const stderr = (result.stderr || '').trim()

  let report = null
  try {
    report = stdout ? JSON.parse(stdout) : null
  } catch {
    report = null
  }

  // `hermes computer-use doctor --json` prints the raw structured
  // health_report payload on success (schema_version, platform,
  // driver_version, overall, checks[]). When cua-driver is missing it
  // exits 2 with a plain-text message instead (doctor.py returns before
  // the json.dump call in that branch) -- report stays null in that case
  // and the plain stdout is what's actually informative, so it's surfaced
  // in the failure detail below.
  if (report && typeof report === 'object' && report.overall) {
    const status = report.overall === 'ok' && result.status === 0 ? 'pass' : 'fail'
    record(
      'doctor',
      status,
      `cua-driver ${report.driver_version || '?'} on ${report.platform || '?'} -- overall=${report.overall} (exit ${result.status})`,
      { report }
    )
    return report
  }

  record(
    'doctor',
    'fail',
    `no JSON report (exit ${result.status}); stdout: ${truncate(stdout, 300) || '(empty)'}` +
      (stderr ? `; stderr: ${truncate(stderr, 300)}` : ''),
    { command: [pythonInfo.python, ...cliArgs] }
  )
  return null
}

// ---------------------------------------------------------------------------
// Step 3: launch Notepad
// ---------------------------------------------------------------------------

function isProcessRunning(imageName) {
  const result = spawnSync('tasklist', ['/FI', `IMAGENAME eq ${imageName}`, '/NH'], {
    encoding: 'utf8',
    timeout: 5000,
    windowsHide: true
  })
  if (result.error || !result.stdout) return false
  return result.stdout.toLowerCase().includes(imageName.toLowerCase())
}

async function stepLaunchNotepad() {
  if (!IS_WINDOWS) {
    record('notepad-launch', 'fail', `this harness only drives notepad.exe on Windows (platform=${process.platform})`)
    return false
  }

  // Clean slate: close any existing Notepad so the capture binds exactly the
  // window we launch. Win11 Notepad is single-instance with tabs and this
  // harness types into it, so a pre-existing/ghost tab could otherwise be
  // what capture() sees and where type() lands. Best-effort; documented in the
  // header so a user running this knows their open Notepad will be closed.
  console.log('  (closing any existing Notepad for a clean test window)')
  spawnSync('taskkill', ['/IM', 'notepad.exe', '/F'], { encoding: 'utf8', timeout: 5000, windowsHide: true })
  await sleep(900)

  const spawnError = await new Promise(resolve => {
    let settled = false
    const finish = err => {
      if (settled) return
      settled = true
      resolve(err || null)
    }
    let child
    try {
      child = spawn('notepad.exe', [], { detached: true, stdio: 'ignore' })
    } catch (err) {
      finish(err)
      return
    }
    child.once('error', finish)
    child.once('spawn', () => {
      child.unref()
      finish(null)
    })
    // Fall through to the tasklist poll regardless -- on Node versions
    // without the 'spawn' event this still resolves promptly, and a real
    // ENOENT fires its 'error' well before this fallback fires anyway.
    setTimeout(() => finish(null), 3000)
  })

  if (spawnError) {
    record('notepad-launch', 'fail', `spawn notepad.exe failed: ${spawnError.message}`)
    return false
  }

  const deadline = Date.now() + 10_000
  while (Date.now() < deadline) {
    if (isProcessRunning('notepad.exe')) {
      record('notepad-launch', 'pass', 'notepad.exe confirmed via tasklist')
      return true
    }
    await sleep(300)
  }
  record('notepad-launch', 'fail', 'notepad.exe did not appear in tasklist within 10s')
  return false
}

function closeNotepadBestEffort() {
  if (!IS_WINDOWS) return
  const result = spawnSync('taskkill', ['/IM', 'notepad.exe', '/F'], {
    encoding: 'utf8',
    timeout: 5000,
    windowsHide: true
  })
  if (result.error) {
    record('notepad-close', 'fail', `best-effort cleanup: ${result.error.message}`)
    return
  }
  if (result.status === 0) {
    record('notepad-close', 'pass', truncate((result.stdout || '').trim().split(/\r?\n/)[0], 200) || 'taskkill ok')
  } else {
    // Very likely "process not found" (already closed) -- cleanup is
    // best-effort and intentionally NOT in REQUIRED_STEPS, so this never
    // gates the exit code.
    record(
      'notepad-close',
      'fail',
      `best-effort cleanup: ${truncate((result.stderr || result.stdout || '').trim().split(/\r?\n/)[0], 200) || `taskkill exit ${result.status}`}`
    )
  }
}

// ---------------------------------------------------------------------------
// Step 4: drive capture -> click -> type -> capture through handle_computer_use
// ---------------------------------------------------------------------------

const DRIVE_STEP_NAMES = [
  'cu-capture-before',
  'cu-click-edit',
  'cu-type-sentinel',
  'cu-capture-after',
  'cu-capture-after-ax',
  'cu-sentinel-verified'
]

let sentinelSeq = 0
// Deliberately avoids Math.random()/Date.now(): pid + a monotonic counter +
// the high-resolution monotonic clock is enough to make this unique for a
// single harness run without either primitive.
function nextSentinel() {
  sentinelSeq += 1
  return `HERMESCU-${process.pid}-${sentinelSeq}-${process.hrtime.bigint().toString(36)}`
}

async function stepDriveComputerUse(pythonInfo) {
  if (!pythonInfo) {
    for (const name of DRIVE_STEP_NAMES) {
      record(name, 'fail', 'no python interpreter resolved; see python-resolved step')
    }
    return
  }

  const sentinel = nextSentinel()
  manifest.sentinel = sentinel

  // All three actions (capture/type/capture) MUST run inside ONE Python
  // process: tool.py's backend context (active pid/window) is per-process
  // module state, so splitting this across multiple `python -c` calls would
  // lose the target between calls. The sentinel/app name are passed as argv
  // (never string-interpolated into the source) to sidestep any quoting
  // hazard.
  const result = spawnSync(pythonInfo.python, ['-c', PY_DRIVER_SOURCE, sentinel, targetApp], {
    cwd: HERMES_ROOT,
    env: buildPythonEnv(pythonInfo, HERMES_ROOT),
    encoding: 'utf8',
    timeout: 90_000,
    maxBuffer: 64 * 1024 * 1024, // a SOM capture can carry a base64 screenshot
    windowsHide: true
  })

  if (result.error) {
    for (const name of DRIVE_STEP_NAMES) record(name, 'fail', `python spawn failed: ${result.error.message}`)
    return
  }

  const payload = parseTrailingJson(result.stdout)
  manifest.drive = {
    exit_code: result.status,
    stderr_tail: truncate(result.stderr, 2000),
    stdout_parsed: Boolean(payload)
  }

  if (!payload) {
    const reason = `driver script produced no parseable JSON (exit ${result.status}); stderr: ${truncate(result.stderr, 500) || '(empty)'}`
    for (const name of DRIVE_STEP_NAMES) record(name, 'fail', reason)
    return
  }
  if (payload.fatal) {
    for (const name of DRIVE_STEP_NAMES) record(name, 'fail', `driver script fatal error: ${payload.fatal}`)
    return
  }

  const byName = new Map((payload.steps || []).map(s => [s.name, s]))
  for (const name of DRIVE_STEP_NAMES) {
    const s = byName.get(name)
    if (!s) {
      record(name, 'fail', 'step missing from driver script output')
      continue
    }
    const status = s.ok ? 'pass' : 'fail'
    const detail =
      name === 'cu-sentinel-verified'
        ? `type ${s.readback_verified ? 'UIA-readback-verified' : s.sentinel_found_after ? 'found-in-capture' : 'NOT verified'} ` +
          `(readback=${s.readback_verified}, found_in_capture=${s.sentinel_found_after}, absent_before=${s.sentinel_absent_before})`
        : s.error || truncate(s.text, 200)
    const rec = record(name, status, detail)
    if (s.image_b64) {
      const file = saveScreenshotForStep(rec, s.image_b64)
      if (file) rec.screenshot = file
    }
  }
}

// ---------------------------------------------------------------------------
// Python driver: capture(som) -> click(center) -> type(sentinel) ->
// capture(som) -> capture(ax) -> assert sentinel present.
//
// Inlined (rather than a second file) for two reasons: this harness owns
// exactly one file, and handle_computer_use's backend context (active
// pid/window) is per-process state -- every action below must run inside
// the SAME python invocation.
//
// Uses String.raw so backslash escapes (e.g. "\n") reach Python exactly as
// written, unprocessed by the JS template literal.
// ---------------------------------------------------------------------------

const PY_DRIVER_SOURCE = String.raw`
import json
import sys


def emit(obj):
    sys.stdout.write(json.dumps(obj))
    sys.stdout.write("\n")
    sys.stdout.flush()


def normalize(resp):
    """Flatten a handle_computer_use() return value into a uniform shape:
    {shape, text, image_b64, width, height, error}. 'resp' is either the
    _multimodal envelope dict (image + text) or a JSON string (AX-only /
    vision-unavailable fallback / plain action result)."""
    if isinstance(resp, dict) and resp.get("_multimodal"):
        meta = resp.get("meta") or {}
        image_b64 = None
        for part in resp.get("content") or []:
            if isinstance(part, dict) and part.get("type") == "image_url":
                url = ((part.get("image_url") or {}).get("url")) or ""
                if "base64," in url:
                    image_b64 = url.split("base64,", 1)[1]
        return {
            "shape": "multimodal",
            "text": str(resp.get("text_summary") or ""),
            "image_b64": image_b64,
            "width": meta.get("width"),
            "height": meta.get("height"),
            "error": None,
        }
    if isinstance(resp, str):
        err = None
        width = height = None
        try:
            parsed = json.loads(resp)
            if isinstance(parsed, dict):
                err = parsed.get("error")
                width = parsed.get("width")
                height = parsed.get("height")
        except Exception:
            pass
        return {
            "shape": "json",
            "text": resp,
            "image_b64": None,
            "width": width,
            "height": height,
            "error": err,
        }
    return {
        "shape": "unknown",
        "text": repr(resp),
        "image_b64": None,
        "width": None,
        "height": None,
        "error": None,
    }


def main():
    sentinel = sys.argv[1] if len(sys.argv) > 1 else ""
    app_name = sys.argv[2] if len(sys.argv) > 2 else "Notepad"
    steps = []

    try:
        from tools.computer_use.tool import handle_computer_use
    except Exception as e:
        emit({"fatal": "import tools.computer_use.tool failed: %r" % (e,), "steps": steps})
        return

    def run(name, call_args, is_action=False):
        entry = {"name": name}
        try:
            resp = handle_computer_use(dict(call_args))
        except Exception as e:
            entry.update({
                "ok": False,
                "error": "%s: %s" % (type(e).__name__, e),
                "text": "",
                "image_b64": None,
                "width": None,
                "height": None,
                "shape": "exception",
            })
            steps.append(entry)
            return entry
        entry.update(normalize(resp))
        ok = not entry.get("error")
        if ok and (entry.get("width") == 0 or entry.get("height") == 0):
            ok = False
            entry["error"] = "capture returned a zero-sized window (target app not found?)"
        if ok and is_action:
            parsed = None
            if isinstance(resp, str):
                try:
                    parsed = json.loads(resp)
                except Exception:
                    parsed = None
            if isinstance(parsed, dict) and parsed.get("ok") is False:
                ok = False
                entry["error"] = parsed.get("message") or "action reported ok=false"
        entry["ok"] = ok
        steps.append(entry)
        return entry

    before = run("cu-capture-before", {"action": "capture", "mode": "som", "app": app_name})

    width, height = before.get("width"), before.get("height")
    if isinstance(width, (int, float)) and isinstance(height, (int, float)) and width > 0 and height > 0:
        run("cu-click-edit", {
            "action": "click",
            "coordinate": [int(width) // 2, int(height) // 2],
        }, is_action=True)
    else:
        steps.append({
            "name": "cu-click-edit",
            "ok": False,
            "shape": "skipped",
            "error": "no usable width/height from cu-capture-before; click skipped",
            "text": "",
            "image_b64": None,
        })

    # Click is best-effort evidence that the pointer primitive works too --
    # cua-driver's type_text targets the pid captured above directly (it does
    # not depend on OS keyboard focus), so a click failure here does not stop
    # the drive; the real proof is the sentinel round-trip below.
    type_step = run("cu-type-sentinel", {"action": "type", "text": sentinel}, is_action=True)

    after_som = run("cu-capture-after", {"action": "capture", "mode": "som", "app": app_name})
    after_ax = run("cu-capture-after-ax", {"action": "capture", "mode": "ax", "app": app_name})

    haystack = "\n".join(s for s in [after_som.get("text"), after_ax.get("text")] if s)
    before_haystack = before.get("text") or ""
    sentinel_found_after = bool(sentinel) and sentinel in haystack
    sentinel_absent_before = bool(sentinel) and sentinel not in before_haystack

    # Authoritative verification: cua-driver's type_text reads the target
    # control's value back via UIA (ValuePattern) after typing and reports
    # "verified via UIA read-back" when the exact text landed. That is the
    # ground truth the OS reports -- stronger than grepping a capture's
    # element labels, where a plain editor's BODY text (e.g. Win11 Notepad's
    # document) never surfaces. We accept EITHER signal so the proof is honest
    # and robust to how a given app exposes its edited text.
    type_text = type_step.get("text") or ""
    readback_verified = "verified via UIA read-back" in type_text
    verified = bool(sentinel) and (sentinel_found_after or readback_verified)

    steps.append({
        "name": "cu-sentinel-verified",
        "ok": verified,
        "sentinel_found_after": sentinel_found_after,
        "sentinel_absent_before": sentinel_absent_before,
        "readback_verified": readback_verified,
        "error": None if verified else (
            "type not confirmed: sentinel absent from post-type capture text AND "
            "no 'verified via UIA read-back' in the type result"
        ),
    })

    emit({"steps": steps, "sentinel": sentinel, "app": app_name})


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        emit({"fatal": "unhandled exception in driver script: %s: %s" % (type(e).__name__, e)})
`

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

async function main() {
  fs.mkdirSync(outDir, { recursive: true })

  try {
    stepDriverPresent()
    const pythonInfo = stepPythonResolved()
    manifest.python = pythonInfo
    stepDoctor(pythonInfo)
    await stepLaunchNotepad()
    await stepDriveComputerUse(pythonInfo)
  } catch (err) {
    record('harness-crash', 'fail', String((err && err.stack) || err))
  } finally {
    closeNotepadBestEffort()
  }

  manifest.finished_at = new Date().toISOString()
  fs.writeFileSync(path.join(outDir, 'run.json'), JSON.stringify(manifest, null, 2))

  // A required step that never ran at all (e.g. an early crash) counts as
  // failed just like an explicit FAIL -- silently missing evidence must
  // never read as a pass.
  const missingOrFailed = [...REQUIRED_STEPS].filter(name => {
    const rec = findStep(name)
    return !rec || rec.status !== 'pass'
  })
  const passCount = manifest.steps.filter(s => s.status === 'pass').length
  console.log(
    `\ndone: ${passCount}/${manifest.steps.length} steps pass; required outstanding: [${missingOrFailed.join(', ') || 'none'}] -> ${outDir}`
  )
  process.exit(missingOrFailed.length ? 1 : 0)
}

main().catch(err => {
  console.error('harness error:', (err && err.stack) || err)
  process.exit(2)
})
