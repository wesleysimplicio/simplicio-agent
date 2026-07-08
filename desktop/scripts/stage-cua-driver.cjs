'use strict'

/**
 * Stage the cua-driver (computer-use) binaries for electron-builder packaging.
 *
 * simplicio-agent's computer-use toolset shells out to a `cua-driver` binary
 * resolved from PATH (tools/computer_use/cua_backend.py's `_CUA_DRIVER_CMD`)
 * -- today that means every desktop user has to install cua-driver
 * separately. This script copies pre-built binaries into
 * desktop/build/bin/<platform>-<arch>/ (the SAME per-platform directory
 * stage-runtime-bin.cjs stages the simplicio kernel into) so they ship inside
 * the packaged app via the shared `bin` extraResources entry;
 * electron/main.cjs's resolveBundledCuaDriverBin() finds cua-driver there and
 * points HERMES_CUA_DRIVER_CMD at it, with no change to cua_backend.py's own
 * PATH-first resolution (an explicit HERMES_CUA_DRIVER_CMD still wins).
 *
 * On win32 this stages BOTH the driver AND its UIAccess worker
 * (cua-driver-uia.exe, spawned by cua-driver itself for elevated-window
 * automation -- see tools/computer_use/permissions.py) side by side, since
 * cua-driver looks for its worker next to its own binary. macOS/Linux ship
 * only the single `cua-driver` binary -- there is no UIA worker there.
 *
 * IMPORTANT: this directory is SHARED with stage-runtime-bin.cjs (the
 * simplicio kernel binary lands in the same desktop/build/bin/<platform>-
 * <arch>/ folder). Unlike that script, this one never wipes the destination
 * directory before writing -- only ADDS/overwrites its own files -- so
 * running this after (or before) stage-runtime-bin.cjs never deletes the
 * other script's staged binary. `npm run build:win` / `dist:win` run
 * `stage:runtime` immediately before `stage:cua-driver` for exactly this
 * reason; keep that order if these scripts are ever reordered.
 *
 * Source resolution: the `CUA_DRIVER_BIN` env var only -- either a directory
 * containing the binaries under their canonical names, or a direct path to
 * the primary cua-driver binary itself (when it's a file, its containing
 * directory is used, so a sibling cua-driver-uia.exe next to it on Windows is
 * still picked up). Unlike stage-runtime-bin.cjs's kernel binary, cua-driver
 * has no sibling-checkout convention to fall back to here -- it's built from
 * a separate upstream project (trycua/cua), not a `simplicio-*` checkout next
 * to this repo -- so an unset CUA_DRIVER_BIN always falls through to the
 * honest degrade below.
 *
 * Honest degradation, matching kernel_binding.py's own rule ("no kernel ->
 * the feature is OFF, we never fabricate a kernel decision") and this repo's
 * stage-runtime-bin.cjs: if no source binary is found, this script logs a
 * clear warning and exits 0 without writing anything -- it does NOT fail the
 * desktop build, since bundling is an enhancement over the existing
 * PATH-lookup fallback (cua_backend.py's `shutil.which`), not a hard
 * requirement. Set CUA_DRIVER_BIN_REQUIRED=1 (CI release builds) to turn that
 * warning into a hard failure instead. The optional Windows UIAccess worker
 * is exempt from that hard-fail even when required -- cua-driver itself
 * degrades gracefully without it (only elevated-window automation is
 * affected), so a missing worker only ever warns.
 *
 * Only stages the HOST platform/arch -- like stage-runtime-bin.cjs /
 * stage-native-deps.cjs, this does not cross-compile; a mac or Windows
 * package must be built (and staged) on that OS.
 */

const fs = require('node:fs')
const path = require('node:path')

const APP_ROOT = path.resolve(__dirname, '..')
const STAGE_ROOT = path.join(APP_ROOT, 'build', 'bin')

const TARGET_PLATFORM = process.platform
const TARGET_ARCH = process.env.npm_config_arch || process.arch
const DRIVER_BIN_NAME = TARGET_PLATFORM === 'win32' ? 'cua-driver.exe' : 'cua-driver'
const UIA_WORKER_BIN_NAME = 'cua-driver-uia.exe'

/** Binaries expected on this platform -- the UIAccess worker is Windows-only. */
function expectedBinaries() {
  return TARGET_PLATFORM === 'win32' ? [DRIVER_BIN_NAME, UIA_WORKER_BIN_NAME] : [DRIVER_BIN_NAME]
}

function isFile(candidate) {
  try {
    return fs.statSync(candidate).isFile()
  } catch {
    return false
  }
}

function isDirectory(candidate) {
  try {
    return fs.statSync(candidate).isDirectory()
  } catch {
    return false
  }
}

/**
 * Resolve the source directory to stage binaries from. CUA_DRIVER_BIN may
 * name a directory (used as-is) or a file (its dirname is used, so a
 * same-directory cua-driver-uia.exe is still found). Returns null when unset
 * or when it points at nothing on disk.
 */
function resolveSourceDir() {
  const override = (process.env.CUA_DRIVER_BIN || '').trim()
  if (!override) return null

  const resolved = path.resolve(override)
  if (isDirectory(resolved)) return resolved
  if (isFile(resolved)) return path.dirname(resolved)
  return null
}

function degrade(message) {
  if (process.env.CUA_DRIVER_BIN_REQUIRED === '1') {
    throw new Error(message.replace('packaging without', 'refusing to package without'))
  }
  console.warn(message)
}

function main() {
  const sourceDir = resolveSourceDir()

  if (!sourceDir) {
    degrade(
      `[stage-cua-driver] no CUA_DRIVER_BIN set (or it does not exist on disk) -- packaging ` +
        `without a bundled cua-driver (computer-use falls back to PATH lookup, per ` +
        `tools/computer_use/cua_backend.py). Set CUA_DRIVER_BIN to a directory or binary path to bundle it.`
    )
    return
  }

  const primarySource = path.join(sourceDir, DRIVER_BIN_NAME)
  if (!isFile(primarySource)) {
    degrade(
      `[stage-cua-driver] CUA_DRIVER_BIN (${sourceDir}) has no ${DRIVER_BIN_NAME} -- packaging ` +
        `without a bundled cua-driver (computer-use falls back to PATH lookup).`
    )
    return
  }

  const destDir = path.join(STAGE_ROOT, `${TARGET_PLATFORM}-${TARGET_ARCH}`)
  fs.mkdirSync(destDir, { recursive: true })

  const staged = []
  const missingOptional = []
  for (const binName of expectedBinaries()) {
    const source = path.join(sourceDir, binName)
    if (!isFile(source)) {
      // Only the primary driver binary is mandatory (checked above); the
      // Windows UIAccess worker is best-effort -- cua-driver itself degrades
      // gracefully without it (elevated-window automation just won't work).
      missingOptional.push(binName)
      continue
    }
    const dest = path.join(destDir, binName)
    fs.copyFileSync(source, dest)
    if (TARGET_PLATFORM !== 'win32') {
      fs.chmodSync(dest, 0o755)
    }
    staged.push(binName)
  }

  console.log(`[stage-cua-driver] staged ${staged.join(', ')} from ${sourceDir} -> ${path.relative(APP_ROOT, destDir)}`)
  if (missingOptional.length > 0) {
    console.warn(
      `[stage-cua-driver] ${missingOptional.join(', ')} not found next to ${DRIVER_BIN_NAME} -- packaging ` +
        `without it (elevated-window automation needs the UIAccess worker; see tools/computer_use/permissions.py).`
    )
  }
}

main()
