'use strict'

/**
 * Stage the simplicio (Rust kernel) binary for electron-builder packaging.
 *
 * simplicio-agent talks to the simplicio-runtime kernel by shelling out to a
 * `simplicio` binary resolved from PATH (tools/kernel_binding.py) -- today
 * that means every desktop user has to install/build simplicio-runtime
 * separately. This script copies a pre-built binary into
 * desktop/build/bin/<platform>-<arch>/ so it can ship inside the packaged
 * app via the `bin` extraResources entry; electron/main.cjs's
 * resolveBundledKernelBin() finds it at process.resourcesPath/bin/... and
 * points HERMES_KERNEL_BIN at it, with no change to kernel_binding.py's own
 * PATH-first resolution (an explicit HERMES_KERNEL_BIN still wins).
 *
 * Source resolution:
 *   1. SIMPLICIO_RUNTIME_BIN env var -- absolute path to the built binary,
 *      for CI or any layout where simplicio-runtime isn't a sibling checkout.
 *   2. Sibling checkout convention -- ../../simplicio-runtime/target/release/
 *      relative to this repo (matches how simplicio-runtime and
 *      simplicio-agent are cloned side by side in this project's own dev
 *      environment).
 *
 * Honest degradation, matching kernel_binding.py's own rule ("no kernel ->
 * the feature is OFF, we never fabricate a kernel decision"): if no source
 * binary is found, this script logs a clear warning and exits 0 without
 * writing anything -- it does NOT fail the desktop build, since bundling is
 * an enhancement over the existing PATH-lookup fallback, not a hard
 * requirement. Set SIMPLICIO_RUNTIME_BIN_REQUIRED=1 (CI release builds) to
 * turn that warning into a hard failure instead.
 *
 * Only stages the HOST platform/arch -- like stage-native-deps.cjs, this
 * does not cross-compile; a mac or Windows package must be built (and
 * staged) on that OS.
 */

const fs = require('node:fs')
const path = require('node:path')

const APP_ROOT = path.resolve(__dirname, '..')
const STAGE_ROOT = path.join(APP_ROOT, 'build', 'bin')

const TARGET_PLATFORM = process.platform
const TARGET_ARCH = process.env.npm_config_arch || process.arch
const BIN_NAME = TARGET_PLATFORM === 'win32' ? 'simplicio.exe' : 'simplicio'

function defaultSourceBin() {
  // desktop/ -> simplicio-agent/ -> siblings/ -> simplicio-runtime/
  return path.resolve(APP_ROOT, '..', '..', 'simplicio-runtime', 'target', 'release', BIN_NAME)
}

function resolveSourceBin() {
  const override = (process.env.SIMPLICIO_RUNTIME_BIN || '').trim()
  return override || defaultSourceBin()
}

function main() {
  const source = resolveSourceBin()
  const destDir = path.join(STAGE_ROOT, `${TARGET_PLATFORM}-${TARGET_ARCH}`)
  const dest = path.join(destDir, BIN_NAME)

  if (!fs.existsSync(source)) {
    const message =
      `[stage-runtime-bin] no simplicio binary at ${source} -- packaging without a ` +
      `bundled kernel (desktop falls back to PATH lookup, per kernel_binding.py). ` +
      `Set SIMPLICIO_RUNTIME_BIN or build simplicio-runtime first to bundle it.`
    if (process.env.SIMPLICIO_RUNTIME_BIN_REQUIRED === '1') {
      throw new Error(message.replace('packaging without', 'refusing to package without'))
    }
    console.warn(message)
    return
  }

  fs.rmSync(destDir, { recursive: true, force: true })
  fs.mkdirSync(destDir, { recursive: true })
  fs.copyFileSync(source, dest)
  if (TARGET_PLATFORM !== 'win32') {
    fs.chmodSync(dest, 0o755)
  }
  console.log(`[stage-runtime-bin] staged ${source} -> ${path.relative(APP_ROOT, dest)}`)
}

main()
