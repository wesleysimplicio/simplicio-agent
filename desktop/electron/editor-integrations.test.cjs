'use strict'

const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')

const {
  detectEditors,
  registerAll,
  parseMcpRegisterOutput,
  fileRegistersSimplicio,
  codeUserDir,
  claudeDesktopConfigPath
} = require('./editor-integrations.cjs')

function makeTempHome() {
  return fs.mkdtempSync(path.join(os.tmpdir(), 'simplicio-editors-'))
}

test('detectEditors reports installed:false/registered:false for a totally empty HOME', () => {
  const home = makeTempHome()
  const editors = detectEditors({ home, platform: 'linux', env: {} })
  assert.equal(editors.length, 8)
  for (const editor of editors) {
    assert.equal(editor.installed, false, `${editor.id} installed`)
    assert.equal(editor.registered, false, `${editor.id} registered`)
    assert.equal(typeof editor.configPath, 'string')
  }
  fs.rmSync(home, { recursive: true, force: true })
})

test('detectEditors marks claude-code installed+registered when ~/.claude.json mentions simplicio', () => {
  const home = makeTempHome()
  fs.writeFileSync(path.join(home, '.claude.json'), JSON.stringify({ mcpServers: { simplicio: {} } }))
  const editors = detectEditors({ home, platform: 'linux', env: {} })
  const claudeCode = editors.find(e => e.id === 'claude-code')
  assert.equal(claudeCode.installed, true)
  assert.equal(claudeCode.registered, true)
  fs.rmSync(home, { recursive: true, force: true })
})

test('detectEditors marks claude-code installed but not registered when the file has no simplicio entry', () => {
  const home = makeTempHome()
  fs.writeFileSync(path.join(home, '.claude.json'), JSON.stringify({ mcpServers: { other: {} } }))
  const editors = detectEditors({ home, platform: 'linux', env: {} })
  const claudeCode = editors.find(e => e.id === 'claude-code')
  assert.equal(claudeCode.installed, true)
  assert.equal(claudeCode.registered, false)
  fs.rmSync(home, { recursive: true, force: true })
})

test('detectEditors resolves claude-desktop config per platform', () => {
  const home = '/home/user'
  const winPath = claudeDesktopConfigPath({ home: 'C:\\Users\\u', platform: 'win32', env: { APPDATA: 'C:\\Users\\u\\AppData\\Roaming' } })
  assert.equal(winPath, path.join('C:\\Users\\u\\AppData\\Roaming', 'Claude', 'claude_desktop_config.json'))

  const macPath = claudeDesktopConfigPath({ home, platform: 'darwin', env: {} })
  assert.equal(macPath, path.join(home, 'Library', 'Application Support', 'Claude', 'claude_desktop_config.json'))

  const linuxPath = claudeDesktopConfigPath({ home, platform: 'linux', env: {} })
  assert.equal(linuxPath, path.join(home, '.config', 'Claude', 'claude_desktop_config.json'))
})

test('detectEditors treats vscode as registered if EITHER the Cline or native mcp.json mentions simplicio', () => {
  const home = makeTempHome()
  const userDir = codeUserDir({ home, platform: 'linux', env: {} })
  fs.mkdirSync(userDir, { recursive: true })
  fs.writeFileSync(path.join(userDir, 'mcp.json'), JSON.stringify({ servers: { simplicio: {} } }))

  const editors = detectEditors({ home, platform: 'linux', env: {} })
  const vscode = editors.find(e => e.id === 'vscode')
  assert.equal(vscode.installed, true)
  assert.equal(vscode.registered, true)
  fs.rmSync(home, { recursive: true, force: true })
})

test('fileRegistersSimplicio is tolerant of a missing file (no throw, false)', () => {
  assert.equal(fileRegistersSimplicio('/definitely/does/not/exist/mcp.json'), false)
})

test('fileRegistersSimplicio is tolerant of malformed JSON as long as the substring is present', () => {
  const home = makeTempHome()
  const file = path.join(home, 'broken.json')
  fs.writeFileSync(file, '{not valid json but mentions simplicio')
  assert.equal(fileRegistersSimplicio(file), true)
  fs.rmSync(home, { recursive: true, force: true })
})

test('parseMcpRegisterOutput extracts both the registered and skipped lists', () => {
  const stdout = [
    'registered Simplicio MCP server in: claude-code, hermes, gemini, claude-desktop, vscode',
    'not installed (skipped): cursor, windsurf, kiro, codex'
  ].join('\n')
  assert.deepEqual(parseMcpRegisterOutput(stdout), {
    registered: ['claude-code', 'hermes', 'gemini', 'claude-desktop', 'vscode'],
    skipped: ['cursor', 'windsurf', 'kiro', 'codex']
  })
})

test('parseMcpRegisterOutput copes with only one of the two lines present', () => {
  assert.deepEqual(parseMcpRegisterOutput('registered Simplicio MCP server in: claude-code'), {
    registered: ['claude-code'],
    skipped: []
  })
  assert.deepEqual(parseMcpRegisterOutput('not installed (skipped): cursor'), {
    registered: [],
    skipped: ['cursor']
  })
  assert.deepEqual(parseMcpRegisterOutput(''), { registered: [], skipped: [] })
})

test('registerAll returns ok:false with an explicit error when the runner reports no binary', async () => {
  const runner = async () => ({ ok: false, stdout: '', stderr: 'simplicio binary not found', code: null })
  const result = await registerAll(runner)
  assert.equal(result.ok, false)
  assert.equal(result.error, 'simplicio binary not found')
  assert.deepEqual(result.registered, [])
  assert.deepEqual(result.skipped, [])
})

test('registerAll parses a successful run into registered/skipped/raw', async () => {
  const stdout = 'registered Simplicio MCP server in: claude-code, vscode\nnot installed (skipped): cursor'
  const runner = async args => {
    assert.deepEqual(args, ['mcp', 'register'])
    return { ok: true, stdout, stderr: '', code: 0 }
  }
  const result = await registerAll(runner)
  assert.equal(result.ok, true)
  assert.deepEqual(result.registered, ['claude-code', 'vscode'])
  assert.deepEqual(result.skipped, ['cursor'])
  assert.equal(result.raw, stdout)
})
