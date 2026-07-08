// One-off evidence capture: boot the real Electron app, navigate to
// Integrations, kick off a REAL headless Claude Code session (spawned as a
// child of this script) against the instrumented Simplicio MCP server, and
// screenshot the app the moment `simplicio mcp status --json` reports the
// connection as alive -- proving the desktop panel reflects a live MCP
// client in real time, not just historical/dead entries.

import { spawn } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { _electron as electron } from 'playwright'

const CLAUDE_BIN = 'C:\\Users\\Z0059V7A\\.local\\bin\\claude.exe'

const DESKTOP_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const OUT_DIR = path.resolve(DESKTOP_ROOT, '..', '.orchestrator', 'evidence', 'mcp-live')
const DEV_URL = 'http://127.0.0.1:5174'
const RUNTIME_BIN = 'C:\\Users\\Z0059V7A\\m\\ai\\simplicio-runtime\\target\\release\\simplicio.exe'
const TEST_DIR = process.argv[2]
if (!TEST_DIR) throw new Error('usage: node live-mcp-capture.mjs <claude-test-dir>')

fs.mkdirSync(OUT_DIR, { recursive: true })

async function devServerUp() {
  try {
    const res = await fetch(DEV_URL, { signal: AbortSignal.timeout(2000) })
    return res.ok
  } catch {
    return false
  }
}

async function main() {
  if (!(await devServerUp())) throw new Error('vite dev server not up on ' + DEV_URL + ' (start it first)')

  const app = await electron.launch({
    args: ['.'],
    cwd: DESKTOP_ROOT,
    env: {
      ...process.env,
      HERMES_DESKTOP_DEV_SERVER: DEV_URL,
      HERMES_DESKTOP_HERMES_ROOT: path.resolve(DESKTOP_ROOT, '..'),
      SIMPLICIO_BIN: RUNTIME_BIN
    }
  })

  let page = null
  const deadline1 = Date.now() + 240_000
  while (!page && Date.now() < deadline1) {
    page = app.windows().find(w => w.url().startsWith(DEV_URL)) || null
    if (!page) await new Promise(r => setTimeout(r, 1000))
  }
  await page.waitForLoadState('domcontentloaded', { timeout: 240_000 })
  await page.waitForSelector('text=/gateway ready/i', { timeout: 180_000 }).catch(() => {})
  console.log('app ready')

  // Navigate to Integrations (sidebar plug icon) so the mcp-connections
  // polling hook mounts and starts its short-interval poll. Try each
  // selector separately -- a comma-joined string mixing CSS and `text=`
  // pseudo-selectors does not union the way plain CSS commas do.
  await page.keyboard.press('Escape').catch(() => {})
  let navigated = false
  for (const sel of ['.codicon-plug', '[aria-label*="ntegra"]', 'text=/^integra/i']) {
    try {
      const loc = page.locator(sel).first()
      await loc.waitFor({ state: 'visible', timeout: 8000 })
      await loc.click()
      navigated = true
      break
    } catch { /* try next selector */ }
  }
  console.log('navigated to integrations:', navigated)
  await page.waitForSelector('text=/mcp/i', { timeout: 30_000 }).catch(() => {})
  await page.screenshot({ path: path.join(OUT_DIR, '01-integrations-before.png') })
  console.log('captured: before (no live claude session yet)')

  // Kick off a REAL Claude Code headless session against the instrumented
  // Simplicio MCP server, from a fresh test dir, with a task substantial
  // enough to keep its MCP child process alive for several seconds.
  const claude = spawn(
    CLAUDE_BIN,
    [
      '-p',
      'Adicione um pequeno placar de melhor pontuacao (localStorage) ao jogo em index.html. Antes de editar, use a ferramenta MCP simplicio_map para orientar-se no arquivo, depois aplique a mudanca com simplicio_edit (plano mecanico), e por fim rode simplicio_validate. Nao reescreva o arquivo inteiro.',
      '--continue',
      '--output-format', 'stream-json',
      '--verbose',
      '--allowedTools', 'Write', 'Read',
      'mcp__simplicio__simplicio_map', 'mcp__simplicio__simplicio_memory',
      'mcp__simplicio__simplicio_edit', 'mcp__simplicio__simplicio_gate',
      'mcp__simplicio__simplicio_validate'
    ],
    { cwd: TEST_DIR, stdio: ['ignore', 'pipe', 'pipe'], shell: false, windowsHide: true }
  )
  let claudeOut = ''
  claude.stdout.on('data', d => { claudeOut += d.toString() })
  claude.stderr.on('data', () => {})
  claude.once('error', err => console.log('claude spawn error:', err.message))
  console.log('claude test session launched, pid', claude.pid)
  // Hard safety timeout: never let this script hang on a stuck/slow session
  // once we already have what we need (the live-connection screenshot).
  const hardKill = setTimeout(() => {
    console.log('hard timeout: killing claude test session')
    try { claude.kill('SIGKILL') } catch { /* already gone */ }
  }, 100_000)
  hardKill.unref?.()

  // Poll `simplicio mcp status --json` until it reports an alive connection
  // whose repo matches the test dir, then screenshot immediately.
  let caughtAlive = false
  const deadline2 = Date.now() + 60_000
  while (!caughtAlive && Date.now() < deadline2) {
    const status = spawn(RUNTIME_BIN, ['mcp', 'status', '--json'], { stdio: ['ignore', 'pipe', 'ignore'] })
    let out = ''
    await new Promise(resolve => {
      status.stdout.on('data', d => { out += d.toString() })
      status.on('close', resolve)
    })
    try {
      const parsed = JSON.parse(out)
      const live = (parsed.connections || []).find(c => c.alive && c.repo === TEST_DIR)
      if (live) {
        console.log('LIVE CONNECTION CAUGHT:', JSON.stringify(live))
        await page.locator('button[aria-label*="efresh"], button:has-text("Refresh")').first().click().catch(() => {})
        await page.waitForTimeout(400)
        await page.screenshot({ path: path.join(OUT_DIR, '02-integrations-live.png') })
        fs.writeFileSync(path.join(OUT_DIR, 'live-connection.json'), JSON.stringify(live, null, 2))
        caughtAlive = true
        break
      }
    } catch { /* status not JSON yet, ignore */ }
    await new Promise(r => setTimeout(r, 500))
  }
  if (!caughtAlive) console.log('WARNING: never caught an alive connection in the poll window')

  // Let claude finish naturally, capture its result for the token report.
  await new Promise(resolve => claude.on('close', resolve))
  fs.writeFileSync(path.join(OUT_DIR, 'claude-session3.jsonl'), claudeOut)
  await page.screenshot({ path: path.join(OUT_DIR, '03-integrations-after.png') })
  console.log('claude session finished, captured after-state')

  await app.close().catch(() => {})
  process.exit(caughtAlive ? 0 : 1)
}

main().catch(err => {
  console.error('capture error:', err)
  process.exit(2)
})
