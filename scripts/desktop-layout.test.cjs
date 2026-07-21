const assert = require('node:assert/strict')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')
const test = require('node:test')

const { resolveDesktopLayout, validateDesktopLayout } = require('./desktop-layout.cjs')

const repoRoot = path.resolve(__dirname, '..')

function makeFixture() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'desktop-layout-'))
  fs.copyFileSync(path.join(repoRoot, 'desktop-layout.json'), path.join(root, 'desktop-layout.json'))
  for (const relative of ['desktop/src', 'desktop/electron', 'apps/shared']) fs.mkdirSync(path.join(root, relative), { recursive: true })
  fs.writeFileSync(path.join(root, 'desktop/package.json'), '{}\n')
  for (const relative of ['.envrc', '.github/workflows/typecheck.yml', 'package.json', 'desktop/README.md', 'desktop/DESIGN.md']) {
    fs.mkdirSync(path.dirname(path.join(root, relative)), { recursive: true })
    fs.writeFileSync(path.join(root, relative), 'desktop/\n')
  }
  return root
}

test('resolves and validates the checked-in desktop layout', () => {
  const layout = resolveDesktopLayout(repoRoot)
  const result = validateDesktopLayout(repoRoot)
  assert.equal(result.ok, true, result.errors.join('\n'))
  assert.equal(path.relative(repoRoot, layout.canonicalRoot), 'desktop')
  assert.equal(path.relative(repoRoot, layout.required.packageJson.path).replaceAll('\\', '/'), 'desktop/package.json')
  assert.equal(fs.existsSync(path.join(repoRoot, 'apps', 'desktop')), false)
})

test('root installs run the persisted desktop layout guard first', () => {
  const packageJson = JSON.parse(fs.readFileSync(path.join(repoRoot, 'package.json'), 'utf8'))
  assert.equal(packageJson.scripts.preinstall, 'npm run check:desktop-layout')
})

test('rejects a stale apps/desktop reference in a declared consumer', () => {
  const root = makeFixture()
  fs.writeFileSync(path.join(root, '.envrc'), 'watch_file apps/desktop/package.json\n')
  const result = validateDesktopLayout(root)
  assert.equal(result.ok, false)
  assert.match(result.errors.join('\n'), /stale desktop root apps\/desktop.*\.envrc/)
})

test('rejects a reintroduced legacy desktop directory', () => {
  const root = makeFixture()
  fs.mkdirSync(path.join(root, 'apps/desktop'), { recursive: true })
  const result = validateDesktopLayout(root)
  assert.equal(result.ok, false)
  assert.match(result.errors.join('\n'), /legacy desktop root must not exist/)
})

test('rejects absolute and traversal paths in the manifest', () => {
  const root = makeFixture()
  const manifestPath = path.join(root, 'desktop-layout.json')
  const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'))
  manifest.required.renderer.path = '../desktop/src'
  fs.writeFileSync(manifestPath, JSON.stringify(manifest))
  assert.throws(() => resolveDesktopLayout(root), /must not traverse/)
  manifest.required.renderer.path = 'C:/outside/desktop/src'
  fs.writeFileSync(manifestPath, JSON.stringify(manifest))
  assert.throws(() => resolveDesktopLayout(root), /must be relative/)
})
