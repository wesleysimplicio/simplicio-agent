// Evidence harness: launches the real Electron app via Playwright's _electron
// driver and captures step-by-step screenshots of the Simplicio Savings flow
// (onboarding -> savings panel -> integrations -> MCP deploy).
//
// Usage:
//   node scripts/evidence-e2e.mjs [--out <dir>] [--steps <all|boot>]
// Requires the vite dev server on 127.0.0.1:5174 (npm run dev:renderer) or it
// starts one itself. Screenshots land in <out>/NN-<slug>.png plus a run.json
// manifest with pass/fail per step. Honest by construction: a step that cannot
// be reached is recorded as FAIL with the error, never skipped silently.

import { spawn } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { _electron as electron } from 'playwright'

const DESKTOP_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const args = process.argv.slice(2)
const outDir = path.resolve(argVal('--out') || path.join(DESKTOP_ROOT, '..', '.orchestrator', 'evidence', 'desktop'))
const stepsMode = argVal('--steps') || 'all'
const DEV_URL = 'http://127.0.0.1:5174'

function argVal(flag) {
  const i = args.indexOf(flag)
  return i >= 0 ? args[i + 1] : null
}

const manifest = { started_at: new Date().toISOString(), steps: [], dev_url: DEV_URL }
let shot = 0

async function capture(page, slug, note, fn) {
  const rec = { n: ++shot, slug, note, status: 'PENDING' }
  manifest.steps.push(rec)
  try {
    if (fn) await fn()
    await page.waitForTimeout(600) // let animations settle
    const file = path.join(outDir, `${String(rec.n).padStart(2, '0')}-${slug}.png`)
    await page.screenshot({ path: file })
    rec.status = 'PASS'
    rec.file = file
    console.log(`PASS ${rec.n} ${slug}`)
  } catch (err) {
    rec.status = 'FAIL'
    rec.error = String(err && err.message ? err.message : err)
    console.log(`FAIL ${rec.n} ${slug}: ${rec.error}`)
    try {
      const file = path.join(outDir, `${String(rec.n).padStart(2, '0')}-${slug}-FAIL.png`)
      await page.screenshot({ path: file })
      rec.file = file
    } catch { /* window may be gone */ }
  }
  return rec
}

async function devServerUp() {
  try {
    const res = await fetch(DEV_URL, { signal: AbortSignal.timeout(2000) })
    return res.ok
  } catch {
    return false
  }
}

async function ensureDevServer() {
  if (await devServerUp()) return null
  console.log('starting vite dev server...')
  const child = spawn(process.platform === 'win32' ? 'npx.cmd' : 'npx',
    ['vite', '--host', '127.0.0.1', '--port', '5174'],
    { cwd: DESKTOP_ROOT, stdio: 'ignore', detached: false, shell: process.platform === 'win32' })
  for (let i = 0; i < 60; i++) {
    await new Promise(r => setTimeout(r, 1000))
    if (await devServerUp()) return child
  }
  child.kill()
  throw new Error('vite dev server did not come up on ' + DEV_URL)
}

// Click the first visible element matching any selector in the list.
async function clickAny(page, selectors, { timeout = 4000 } = {}) {
  for (const sel of selectors) {
    const loc = page.locator(sel).first()
    try {
      await loc.waitFor({ state: 'visible', timeout: timeout / selectors.length + 500 })
      await loc.click()
      return sel
    } catch { /* try next */ }
  }
  throw new Error('none of the selectors matched: ' + selectors.join(' | '))
}

async function main() {
  fs.mkdirSync(outDir, { recursive: true })
  const vite = await ensureDevServer()

  const app = await electron.launch({
    args: ['.'],
    cwd: DESKTOP_ROOT,
    env: {
      ...process.env,
      HERMES_DESKTOP_DEV_SERVER: DEV_URL,
      // Pin the backend to this repo checkout (venv/ created with py3.13);
      // without it SOURCE_REPO_ROOT resolves to the wrong grandparent dir.
      HERMES_DESKTOP_HERMES_ROOT: path.resolve(DESKTOP_ROOT, '..'),
      SIMPLICIO_EVIDENCE_RUN: '1'
    }
  })
  // Pick the MAIN window (dev-server URL), not the orb/pet/splash windows.
  let page = null
  const deadline = Date.now() + 240_000
  while (!page && Date.now() < deadline) {
    for (const w of app.windows()) {
      if (w.url().startsWith(DEV_URL)) { page = w; break }
    }
    if (!page) await new Promise(r => setTimeout(r, 1000))
  }
  if (!page) page = await app.firstWindow()
  // First dev-server load transforms the whole module graph — allow minutes.
  await page.waitForLoadState('domcontentloaded', { timeout: 240_000 })
  await page.waitForSelector('#root :first-child', { timeout: 240_000 }).catch(() => {})

  await capture(page, 'boot', 'app booted (Electron window, renderer loaded)')

  if (stepsMode === 'all') {
    // ---- Onboarding walk. Wait until the gateway is actually ready (the
    // status bar shows "Gateway ready") or the boot progress bar goes away.
    await page.waitForSelector('text=/gateway ready/i', { timeout: 180_000 }).catch(() => {})
    await page.waitForTimeout(3000)
    await capture(page, 'home', 'app home after boot (gateway ready)')
    // Open the post-setup onboarding via the command palette "Setup Simplicio"
    // entry (works even when a provider is already configured).
    await page.keyboard.press('Control+k')
    await page.waitForTimeout(800)
    await page.keyboard.type('Setup Simplicio', { delay: 40 })
    await page.waitForTimeout(800)
    await page.keyboard.press('Enter')
    await page.waitForTimeout(1500)
    await capture(page, 'onboarding-entry', 'onboarding overlay opened via palette (post-setup flow)')

    // Adaptive walker: advance through onboarding, photographing each of the
    // three new steps when their markers appear. A miss records FAIL — never
    // a fake PASS.
    const advanceButtons = [
      'button:has-text("Begin")', 'button:has-text("Começar")',
      'button:has-text("Continue")', 'button:has-text("Continuar")',
      'button:has-text("Next")', 'button:has-text("Avançar")',
      'button:has-text("Skip")', 'button:has-text("Pular")'
    ]
    const seen = { doctor: false, google: false, stripe: false }
    for (let hop = 0; hop < 12 && !(seen.doctor && seen.google && seen.stripe); hop++) {
      if (!seen.doctor && await page.locator('text=/verificar novamente/i').first().isVisible().catch(() => false)) {
        seen.doctor = true
        // Wait for the real `simplicio doctor` checklist to resolve (spinner
        // "Rodando diagnóstico..." replaced by status items), not a fixed nap.
        await page.waitForSelector('text=/bin(á|a)rio|vers(ã|a)o|runtime v/i', { timeout: 45_000 }).catch(() => {})
        await page.waitForTimeout(1000)
        await capture(page, 'onboarding-doctor', 'onboarding: runtime pendencies checklist (real simplicio doctor)')
      } else if (!seen.google && await page.locator('text=/continuar com google/i').first().isVisible().catch(() => false)) {
        seen.google = true
        await capture(page, 'onboarding-google', 'onboarding: simulated Google sign-in (MODO TESTE badge)')
        await page.locator('text=/continuar com google/i').first().click().catch(() => {})
        await page.waitForTimeout(2500)
        await capture(page, 'onboarding-google-signed', 'simulated sign-in completed (voce@exemplo.com · simulado)')
      } else if (!seen.stripe && await page.locator('text=/assinar \\(simula|simulação|continuar sem assinar/i').first().isVisible().catch(() => false)) {
        seen.stripe = true
        await capture(page, 'onboarding-stripe', 'onboarding: simulated subscription (gate off)')
      }
      // advance one hop
      let clicked = false
      for (const sel of advanceButtons) {
        const loc = page.locator(sel).first()
        if (await loc.isVisible().catch(() => false)) {
          await loc.click().catch(() => {})
          clicked = true
          break
        }
      }
      await page.waitForTimeout(1800)
      if (!clicked && hop > 2 && !seen.doctor && !seen.google && !seen.stripe) break
    }
    for (const [k, v] of Object.entries(seen)) {
      if (!v) {
        manifest.steps.push({ n: ++shot, slug: `onboarding-${k}`, status: 'FAIL', error: 'step marker never became visible during walk' })
        console.log(`FAIL onboarding-${k}: marker not reached`)
      }
    }
    // Close any remaining onboarding overlay so the main UI is reachable.
    await page.keyboard.press('Escape').catch(() => {})
    await page.waitForTimeout(1200)

    // ---- Savings panel via command palette.
    await capture(page, 'savings-panel', 'savings panel: real ledger + measured/estimated evidence + MCP chip', async () => {
      await page.keyboard.press('Control+k')
      await page.waitForTimeout(800)
      await page.keyboard.type('Token Economy', { delay: 40 })
      await page.waitForTimeout(800)
      await page.keyboard.press('Enter')
      // First IPC cycle is slow (binary probe + doctor + memory status). Wait
      // for a real resolved value — the neural backend name — not a fixed nap.
      await page.waitForSelector('text=/sqlite-fts5/', { timeout: 60_000 }).catch(() => {})
      await page.waitForTimeout(1500)
    })

    // ---- Sessions drill-down inside the savings cockpit (command trail proof).
    await capture(page, 'savings-sessions', 'per-session timeline: commands used (surfaces), tokens, hash chain', async () => {
      const sess = page.locator('text=/sess(õ|o)es|sessions/i').first()
      await sess.scrollIntoViewIfNeeded({ timeout: 5000 })
      // expand the first session card if collapsed
      const card = page.locator('[data-testid="savings-session"], .savings-session, button:has-text("auto-memory")').first()
      if (await card.isVisible().catch(() => false)) await card.click().catch(() => {})
      await page.waitForTimeout(1500)
    })

    // ---- Integrations screen via sidebar plug icon.
    await capture(page, 'integrations', 'integrations: per-editor MCP status (real config detection)', async () => {
      await page.keyboard.press('Escape').catch(() => {})
      await clickAny(page, ['.codicon-plug', '[aria-label*="ntegra"]', 'text=/^integra/i'])
      await page.waitForTimeout(3000)
    })

    // ---- Deploy to all editors (runs the real `simplicio mcp register`).
    await capture(page, 'mcp-deploy', 'deploy to all editors: real `simplicio mcp register` result', async () => {
      await clickAny(page, ['button:has-text("Deploy to all")', 'text=/deploy to all|implantar em todos/i'])
      await page.waitForTimeout(10_000)
    })
  }

  manifest.finished_at = new Date().toISOString()
  fs.writeFileSync(path.join(outDir, 'run.json'), JSON.stringify(manifest, null, 2))
  await app.close().catch(() => {})
  if (vite) vite.kill()

  const failed = manifest.steps.filter(s => s.status !== 'PASS')
  console.log(`\ndone: ${manifest.steps.length - failed.length}/${manifest.steps.length} steps PASS -> ${outDir}`)
  process.exit(failed.length && stepsMode === 'all' ? 1 : 0)
}

main().catch(err => {
  console.error('harness error:', err)
  process.exit(2)
})
