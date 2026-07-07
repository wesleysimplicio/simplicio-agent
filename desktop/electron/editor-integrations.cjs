'use strict'

/**
 * editor-integrations.cjs
 *
 * Detects, per supported editor/agent-tool, whether it's installed on this
 * machine and whether it already has the Simplicio MCP server registered --
 * plus a thin wrapper around `simplicio mcp register` to register it
 * everywhere in one shot. Read-only detection is tolerant by construction: a
 * missing file/dir means `false`, a malformed config file means
 * `registered:false`, and nothing here ever throws for a normal "not set up
 * yet" machine.
 *
 * Kept electron-free so it's unit-testable with `node --test` against a fake
 * HOME (same DI pattern as the other electron/*.cjs modules).
 */

const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')
const { runSimplicio } = require('./simplicio-bin.cjs')

/** True iff `targetPath` exists (file or directory). Never throws. */
function pathExists(targetPath) {
  try {
    fs.statSync(targetPath)
    return true
  } catch {
    return false
  }
}

/** Read a file as UTF-8 text, or null if it doesn't exist / can't be read. Never throws. */
function readFileTolerant(filePath) {
  try {
    return fs.readFileSync(filePath, 'utf8')
  } catch {
    return null
  }
}

/** True iff the config file at `filePath` exists and its raw text mentions "simplicio". */
function fileRegistersSimplicio(filePath) {
  const text = readFileTolerant(filePath)
  return typeof text === 'string' && text.includes('simplicio')
}

/** True iff ANY of `filePaths` mentions "simplicio" (used where an editor has multiple config locations). */
function anyFileRegistersSimplicio(filePaths) {
  return filePaths.some(fileRegistersSimplicio)
}

/**
 * Resolve the per-OS "Code/User"-style base directory VS Code (and Cline)
 * store their user config/extension settings under.
 */
function codeUserDir({ home, platform, env }) {
  if (platform === 'win32') {
    const appData = env.APPDATA || path.join(home, 'AppData', 'Roaming')
    return path.join(appData, 'Code', 'User')
  }
  if (platform === 'darwin') {
    return path.join(home, 'Library', 'Application Support', 'Code', 'User')
  }
  return path.join(home, '.config', 'Code', 'User')
}

/** Resolve the per-OS Claude Desktop config file path. */
function claudeDesktopConfigPath({ home, platform, env }) {
  if (platform === 'win32') {
    const appData = env.APPDATA || path.join(home, 'AppData', 'Roaming')
    return path.join(appData, 'Claude', 'claude_desktop_config.json')
  }
  if (platform === 'darwin') {
    return path.join(home, 'Library', 'Application Support', 'Claude', 'claude_desktop_config.json')
  }
  return path.join(home, '.config', 'Claude', 'claude_desktop_config.json')
}

/**
 * Build the editor descriptor list for the current (or injected) machine.
 * Each descriptor's `installed`/`registered` are plain booleans computed
 * eagerly, and `configPath` is the primary config file checked.
 *
 * @param {object} [ctx]
 * @param {string} [ctx.home] - defaults to os.homedir()
 * @param {string} [ctx.platform] - defaults to process.platform
 * @param {object} [ctx.env] - defaults to process.env
 */
function detectEditors(ctx = {}) {
  const home = ctx.home || os.homedir()
  const platform = ctx.platform || process.platform
  const env = ctx.env || process.env
  const resolved = { home, platform, env }

  const claudeCodeConfig = path.join(home, '.claude.json')
  const claudeDesktopConfig = claudeDesktopConfigPath(resolved)
  const cursorConfig = path.join(home, '.cursor', 'mcp.json')
  const codeUser = codeUserDir(resolved)
  const clineConfig = path.join(codeUser, 'globalStorage', 'saoudrizwan.claude-dev', 'settings', 'cline_mcp_settings.json')
  const vscodeNativeConfig = path.join(codeUser, 'mcp.json')
  const codexConfig = path.join(home, '.codex', 'config.toml')
  const antigravityConfig = path.join(home, '.gemini', 'config', 'mcp_config.json')
  const kiroConfig = path.join(home, '.kiro', 'settings', 'mcp.json')
  const hermesConfig = path.join(home, '.hermes', 'mcp.json')

  return [
    {
      id: 'claude-code',
      name: 'Claude Code',
      installed: pathExists(claudeCodeConfig),
      registered: fileRegistersSimplicio(claudeCodeConfig),
      configPath: claudeCodeConfig
    },
    {
      id: 'claude-desktop',
      name: 'Claude Desktop',
      installed: pathExists(path.dirname(claudeDesktopConfig)),
      registered: fileRegistersSimplicio(claudeDesktopConfig),
      configPath: claudeDesktopConfig
    },
    {
      id: 'cursor',
      name: 'Cursor',
      installed: pathExists(path.join(home, '.cursor')),
      registered: fileRegistersSimplicio(cursorConfig),
      configPath: cursorConfig
    },
    {
      id: 'vscode',
      name: 'VS Code (Cline / native MCP)',
      installed: pathExists(codeUser),
      registered: anyFileRegistersSimplicio([clineConfig, vscodeNativeConfig]),
      configPath: vscodeNativeConfig
    },
    {
      id: 'codex',
      name: 'Codex',
      installed: pathExists(path.join(home, '.codex')),
      registered: fileRegistersSimplicio(codexConfig),
      configPath: codexConfig
    },
    {
      id: 'antigravity',
      name: 'Antigravity (Gemini)',
      installed: pathExists(path.join(home, '.gemini')),
      registered: fileRegistersSimplicio(antigravityConfig),
      configPath: antigravityConfig
    },
    {
      id: 'kiro',
      name: 'Kiro',
      installed: pathExists(path.join(home, '.kiro')),
      registered: fileRegistersSimplicio(kiroConfig),
      configPath: kiroConfig
    },
    {
      id: 'hermes',
      name: 'Hermes',
      installed: pathExists(path.join(home, '.hermes')),
      registered: fileRegistersSimplicio(hermesConfig),
      configPath: hermesConfig
    }
  ]
}

/** Split a comma-separated list from `simplicio mcp register` output into trimmed, non-empty entries. */
function splitEditorList(raw) {
  return String(raw || '')
    .split(',')
    .map(entry => entry.trim())
    .filter(Boolean)
}

/**
 * Parse `simplicio mcp register`'s stdout, which reports two lines:
 *   "registered Simplicio MCP server in: claude-code, hermes, gemini, ..."
 *   "not installed (skipped): cursor, windsurf, kiro, ..."
 * Either line may be absent (e.g. nothing to register, or nothing skipped).
 */
function parseMcpRegisterOutput(stdout) {
  const text = String(stdout || '')
  const registeredMatch = text.match(/registered[^\n:]*:\s*([^\n]+)/i)
  const skippedMatch = text.match(/not installed \(skipped\):\s*([^\n]+)/i)
  return {
    registered: registeredMatch ? splitEditorList(registeredMatch[1]) : [],
    skipped: skippedMatch ? splitEditorList(skippedMatch[1]) : []
  }
}

/**
 * Run `simplicio mcp register` and return the parsed result. Never throws --
 * an unresolved binary or a failed run comes back as `ok:false` with an
 * explicit `error`, empty lists, and the raw output for debugging.
 *
 * @param {Function} [runner] - runSimplicio stand-in (tests).
 */
async function registerAll(runner = runSimplicio) {
  const result = await runner(['mcp', 'register'])

  if (!result.stdout && !result.ok) {
    return {
      ok: false,
      registered: [],
      skipped: [],
      raw: result.stderr || '',
      error: result.stderr || 'simplicio mcp register failed'
    }
  }

  const { registered, skipped } = parseMcpRegisterOutput(result.stdout)
  return {
    ok: result.ok,
    registered,
    skipped,
    raw: result.stdout,
    ...(result.ok ? {} : { error: result.stderr || 'simplicio mcp register exited with a non-zero status' })
  }
}

module.exports = {
  detectEditors,
  registerAll,
  parseMcpRegisterOutput,
  pathExists,
  readFileTolerant,
  fileRegistersSimplicio,
  anyFileRegistersSimplicio,
  codeUserDir,
  claudeDesktopConfigPath
}
