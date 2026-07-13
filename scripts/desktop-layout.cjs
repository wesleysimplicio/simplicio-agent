#!/usr/bin/env node

const fs = require('node:fs')
const path = require('node:path')

const MANIFEST_NAME = 'desktop-layout.json'
const STALE_ROOT = 'apps/desktop'

class DesktopLayoutError extends Error {
  constructor(message) {
    super(message)
    this.name = 'DesktopLayoutError'
  }
}

function assertRelativePath(value, label) {
  if (typeof value !== 'string' || value.trim() === '') {
    throw new DesktopLayoutError(`${label} must be a non-empty relative path`)
  }
  const normalized = value.replaceAll('\\', '/')
  if (path.posix.isAbsolute(normalized) || /^[A-Za-z]:\//.test(normalized)) {
    throw new DesktopLayoutError(`${label} must be relative: ${value}`)
  }
  if (normalized.split('/').includes('..')) {
    throw new DesktopLayoutError(`${label} must not traverse its root: ${value}`)
  }
}

function resolveRelative(root, value, label) {
  assertRelativePath(value, label)
  return path.resolve(root, ...value.replaceAll('\\', '/').split('/'))
}

function readManifest(repoRoot) {
  const manifestPath = path.join(repoRoot, MANIFEST_NAME)
  let manifest
  try {
    manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'))
  } catch (error) {
    throw new DesktopLayoutError(`cannot read ${MANIFEST_NAME}: ${error.message}`)
  }
  if (manifest.schemaVersion !== 1) {
    throw new DesktopLayoutError(`unsupported ${MANIFEST_NAME} schemaVersion`)
  }
  if (!manifest.required || typeof manifest.required !== 'object') {
    throw new DesktopLayoutError(`${MANIFEST_NAME} must define required paths`)
  }
  if (!Array.isArray(manifest.consumers)) {
    throw new DesktopLayoutError(`${MANIFEST_NAME} must define consumers`)
  }
  return manifest
}

function resolveDesktopLayout(repoRoot = process.cwd()) {
  const root = path.resolve(repoRoot)
  const manifest = readManifest(root)
  const canonicalRoot = resolveRelative(root, manifest.canonicalRoot, 'canonicalRoot')
  const legacyRoots = (manifest.legacyRoots || []).map((entry, index) =>
    resolveRelative(root, entry, `legacyRoots[${index}]`)
  )
  const required = {}
  for (const [name, spec] of Object.entries(manifest.required)) {
    if (!spec || typeof spec !== 'object') {
      throw new DesktopLayoutError(`required.${name} must be an object`)
    }
    if (spec.type !== 'file' && spec.type !== 'directory') {
      throw new DesktopLayoutError(`required.${name}.type must be file or directory`)
    }
    required[name] = {
      path: resolveRelative(root, spec.path, `required.${name}.path`),
      type: spec.type
    }
  }
  const consumers = manifest.consumers.map((entry, index) =>
    resolveRelative(root, entry, `consumers[${index}]`)
  )
  return Object.freeze({ root, manifestPath: path.join(root, MANIFEST_NAME), canonicalRoot, legacyRoots, required, consumers })
}

function validateDesktopLayout(repoRoot = process.cwd()) {
  const layout = resolveDesktopLayout(repoRoot)
  const errors = []
  if (!fs.existsSync(layout.canonicalRoot) || !fs.statSync(layout.canonicalRoot).isDirectory()) {
    errors.push(`canonical desktop root is missing: ${path.relative(layout.root, layout.canonicalRoot)}`)
  }
  for (const legacyRoot of layout.legacyRoots) {
    if (fs.existsSync(legacyRoot)) {
      errors.push(`legacy desktop root must not exist: ${path.relative(layout.root, legacyRoot)}`)
    }
  }
  for (const [name, spec] of Object.entries(layout.required)) {
    const exists = fs.existsSync(spec.path)
    const matchesType = exists && (spec.type === 'file' ? fs.statSync(spec.path).isFile() : fs.statSync(spec.path).isDirectory())
    if (!matchesType) {
      errors.push(`required.${name} is missing or has the wrong type: ${path.relative(layout.root, spec.path)}`)
    }
  }
  for (const consumer of layout.consumers) {
    if (!fs.existsSync(consumer) || !fs.statSync(consumer).isFile()) {
      errors.push(`consumer is missing: ${path.relative(layout.root, consumer)}`)
      continue
    }
    if (fs.readFileSync(consumer, 'utf8').includes(STALE_ROOT)) {
      errors.push(`consumer references stale desktop root ${STALE_ROOT}: ${path.relative(layout.root, consumer)}`)
    }
  }
  return { ok: errors.length === 0, errors, layout }
}

function publicLayout(layout) {
  return {
    root: layout.root,
    canonicalRoot: layout.canonicalRoot,
    legacyRoots: layout.legacyRoots,
    required: Object.fromEntries(Object.entries(layout.required).map(([name, spec]) => [name, spec.path]))
  }
}

function main(argv) {
  const rootIndex = argv.findIndex((value) => value === '--root')
  const repoRoot = rootIndex === -1 ? process.cwd() : argv[rootIndex + 1]
  if (!repoRoot || repoRoot.startsWith('--')) throw new DesktopLayoutError('--root requires a repository path')
  const result = validateDesktopLayout(repoRoot)
  const pathIndex = argv.findIndex((value) => value === '--path')
  if (pathIndex !== -1) {
    const key = argv[pathIndex + 1]
    if (!key) throw new DesktopLayoutError('--path requires a manifest key')
    const resolved = key === 'canonicalRoot' ? result.layout.canonicalRoot : result.layout.required[key]?.path
    if (!resolved) throw new DesktopLayoutError(`unknown desktop layout path: ${key}`)
    if (!result.ok) throw new DesktopLayoutError(result.errors.join('; '))
    process.stdout.write(`${resolved}\n`)
    return
  }
  process.stdout.write(`${JSON.stringify({ ok: result.ok, errors: result.errors, layout: publicLayout(result.layout) })}\n`)
  if (!result.ok) process.exitCode = 1
}

if (require.main === module) {
  try {
    main(process.argv.slice(2))
  } catch (error) {
    process.stderr.write(`${JSON.stringify({ ok: false, error: error.message })}\n`)
    process.exitCode = 1
  }
}

module.exports = { DesktopLayoutError, resolveDesktopLayout, validateDesktopLayout }
