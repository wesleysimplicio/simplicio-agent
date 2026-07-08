import path from 'node:path'
import { _electron as electron } from 'playwright'

const DESKTOP_ROOT = 'C:\\Users\\Z0059V7A\\m\\ai\\simplicio-agent\\desktop'
const OUT = 'C:\\Users\\Z0059V7A\\m\\ai\\simplicio-agent\\.orchestrator\\evidence\\billing'
const DEV_URL = 'http://127.0.0.1:5174'
const RUNTIME_BIN = 'C:\\Users\\Z0059V7A\\m\\ai\\simplicio-runtime\\target\\release\\simplicio.exe'

const fs = await import('node:fs')
fs.mkdirSync(OUT, { recursive: true })

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
const deadline = Date.now() + 240_000
while (!page && Date.now() < deadline) {
  page = app.windows().find(w => w.url().startsWith(DEV_URL)) || null
  if (!page) await new Promise(r => setTimeout(r, 1000))
}
await page.waitForLoadState('domcontentloaded', { timeout: 240_000 })
await page.waitForSelector('text=/gateway ready/i', { timeout: 180_000 }).catch(() => {})
console.log('app ready')

// Close any restored overlay from a prior run's persisted state, then click
// the real titlebar settings-gear icon directly.
await page.keyboard.press('Escape').catch(() => {})
await page.waitForTimeout(500)
await page.locator('.codicon-settings-gear').first().click()
console.log('opened settings via gear icon')
await page.waitForTimeout(1500)

for (const sel of ['text=/cobran[cç]a/i', 'text=/billing/i']) {
  try {
    const loc = page.locator(sel).first()
    await loc.waitFor({ state: 'visible', timeout: 8000 })
    await loc.click()
    console.log('clicked billing nav via', sel)
    break
  } catch { /* try next */ }
}
await page.waitForTimeout(2500)
await page.screenshot({ path: path.join(OUT, 'billing-settings.png') })
console.log('captured billing screen')

await app.close().catch(() => {})
process.exit(0)
