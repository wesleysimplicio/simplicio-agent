'use strict'

const test = require('node:test')
const assert = require('node:assert/strict')
const path = require('node:path')
const { EventEmitter } = require('node:events')

const {
  resolveSimplicioBin,
  findSimplicioOnPath,
  runSimplicio,
  buildSpawnInvocation,
  isCmdShim,
  probeSimplicioBin,
  parseSimplicioJsonOutput
} = require('./simplicio-bin.cjs')

test('resolveSimplicioBin honors SIMPLICIO_BIN when it exists', () => {
  const exists = p => p === '/custom/simplicio'
  const result = resolveSimplicioBin({
    env: { SIMPLICIO_BIN: '/custom/simplicio', PATH: '' },
    platform: 'linux',
    homedir: '/home/user',
    exists
  })
  assert.deepEqual(result, { bin: '/custom/simplicio', source: 'env:SIMPLICIO_BIN' })
})

test('resolveSimplicioBin ignores SIMPLICIO_BIN when the file does not exist', () => {
  const localBin = path.join('/home/user', '.local', 'bin', 'simplicio.cmd')
  const exists = p => p === localBin
  const result = resolveSimplicioBin({
    env: { SIMPLICIO_BIN: '/does/not/exist', PATH: '' },
    platform: 'win32',
    homedir: '/home/user',
    exists
  })
  assert.deepEqual(result, { bin: localBin, source: 'local-bin' })
})

test('resolveSimplicioBin finds simplicio on PATH before the local-bin fallback', () => {
  const exists = p => p === path.join('/usr/bin', 'simplicio')
  const result = resolveSimplicioBin({
    env: { PATH: ['/usr/bin', '/other/bin'].join(path.delimiter) },
    platform: 'linux',
    homedir: '/home/user',
    exists
  })
  assert.deepEqual(result, { bin: path.join('/usr/bin', 'simplicio'), source: 'path' })
})

test('resolveSimplicioBin falls back to the dev-checkout binary when PATH misses', () => {
  const devBin = path.join('/home/user', 'm', 'ai', 'simplicio', 'simplicio.exe')
  const exists = p => p === devBin
  const result = resolveSimplicioBin({
    env: { PATH: '' },
    platform: 'win32',
    homedir: '/home/user',
    exists
  })
  assert.deepEqual(result, { bin: devBin, source: 'dev-fallback' })
})

// EINVAL regression (CVE-2024-27980 mitigation): a real .exe must always win
// over a .cmd wrapper, because Node can spawn the .exe directly while the
// .cmd needs the cmd.exe indirection.
test('resolveSimplicioBin prefers the dev .exe over the local-bin .cmd when both exist', () => {
  const devBin = path.join('/home/user', 'm', 'ai', 'simplicio', 'simplicio.exe')
  const localBin = path.join('/home/user', '.local', 'bin', 'simplicio.cmd')
  const exists = p => p === devBin || p === localBin
  const result = resolveSimplicioBin({
    env: { PATH: '' },
    platform: 'win32',
    homedir: '/home/user',
    exists
  })
  assert.deepEqual(result, { bin: devBin, source: 'dev-fallback' })
})

test('findSimplicioOnPath prefers simplicio.exe over simplicio.cmd even in a later PATH dir', () => {
  const cmdShim = path.join('C:\\early', 'simplicio.cmd')
  const realExe = path.join('C:\\late', 'simplicio.exe')
  const exists = p => p === cmdShim || p === realExe
  const found = findSimplicioOnPath(['C:\\early', 'C:\\late'].join(path.delimiter), true, exists)
  assert.equal(found, realExe)
})

// Real machine state that motivated the probe: a pip-installed
// `simplicio.exe` launcher stub on PATH exists on disk but exits 1 on every
// invocation (it tries to download a binary and dies). Existence alone must
// not win — a candidate that fails the live probe is skipped for the next
// rung.
test('resolveSimplicioBin skips a PATH candidate that exists but fails the verify probe', () => {
  const brokenStub = path.join('C:\\python\\Scripts', 'simplicio.exe')
  const devBin = path.join('/home/user', 'm', 'ai', 'simplicio', 'simplicio.exe')
  const exists = p => p === brokenStub || p === devBin
  const probed = []
  const result = resolveSimplicioBin({
    env: { PATH: 'C:\\python\\Scripts' },
    platform: 'win32',
    homedir: '/home/user',
    exists,
    verify: bin => {
      probed.push(bin)
      return bin !== brokenStub
    }
  })
  assert.deepEqual(result, { bin: devBin, source: 'dev-fallback' })
  assert.ok(probed.includes(brokenStub), 'the broken stub should have been probed and rejected')
})

test('resolveSimplicioBin returns null when every existing candidate fails the probe', () => {
  const result = resolveSimplicioBin({
    env: { PATH: '' },
    platform: 'win32',
    homedir: '/home/user',
    exists: () => true,
    verify: () => false
  })
  assert.equal(result, null)
})

test('resolveSimplicioBin returns null when nothing resolves', () => {
  const result = resolveSimplicioBin({
    env: { PATH: '' },
    platform: 'linux',
    homedir: '/home/user',
    exists: () => false
  })
  assert.equal(result, null)
})

test('findSimplicioOnPath tries every PATHEXT candidate on Windows', () => {
  const exists = p => p === path.join('C:\\bin', 'simplicio.cmd')
  const found = findSimplicioOnPath('C:\\bin', true, exists)
  assert.equal(found, path.join('C:\\bin', 'simplicio.cmd'))
})

test('findSimplicioOnPath returns null when no directory has the binary', () => {
  const found = findSimplicioOnPath('/a:/b', false, () => false)
  assert.equal(found, null)
})

test('runSimplicio reports ok:false with an explicit error when the binary is not found', async () => {
  const result = await runSimplicio(['doctor'], { env: { PATH: '' }, homedir: '/nowhere', exists: () => false })
  assert.equal(result.ok, false)
  assert.equal(result.stdout, '')
  assert.match(result.stderr, /simplicio binary not found/)
  assert.equal(result.code, null)
})

test('runSimplicio captures stdout/stderr and a zero exit as ok:true', async () => {
  const spawnFn = () => {
    const child = new EventEmitter()
    child.stdout = new EventEmitter()
    child.stderr = new EventEmitter()
    child.kill = () => {}
    setImmediate(() => {
      child.stdout.emit('data', Buffer.from('{"ok":true}\n'))
      child.emit('exit', 0, null)
    })
    return child
  }
  const result = await runSimplicio(['doctor', '--json'], {
    resolved: { bin: '/bin/simplicio', source: 'test' },
    spawnFn
  })
  assert.equal(result.ok, true)
  assert.equal(result.code, 0)
  assert.equal(result.stdout, '{"ok":true}\n')
  assert.equal(result.stderr, '')
})

test('runSimplicio reports ok:false for a non-zero exit', async () => {
  const spawnFn = () => {
    const child = new EventEmitter()
    child.stdout = new EventEmitter()
    child.stderr = new EventEmitter()
    child.kill = () => {}
    setImmediate(() => {
      child.stderr.emit('data', Buffer.from('boom'))
      child.emit('exit', 1, null)
    })
    return child
  }
  const result = await runSimplicio(['doctor'], {
    resolved: { bin: '/bin/simplicio', source: 'test' },
    spawnFn
  })
  assert.equal(result.ok, false)
  assert.equal(result.code, 1)
  assert.equal(result.stderr, 'boom')
})

test('runSimplicio surfaces a spawn error() event as ok:false', async () => {
  const spawnFn = () => {
    const child = new EventEmitter()
    child.stdout = new EventEmitter()
    child.stderr = new EventEmitter()
    child.kill = () => {}
    setImmediate(() => child.emit('error', new Error('ENOENT')))
    return child
  }
  const result = await runSimplicio(['doctor'], {
    resolved: { bin: '/bin/simplicio', source: 'test' },
    spawnFn
  })
  assert.equal(result.ok, false)
  assert.match(result.stderr, /ENOENT/)
})

// Distinct fake bin paths per test: probeSimplicioBin caches by path for the
// process lifetime, so reusing a path across tests would leak results.
test('probeSimplicioBin accepts a binary whose --help lists the savings commands', () => {
  const ok = probeSimplicioBin('C:\\fake\\runtime-a\\simplicio.exe', {
    execFileSyncFn: () => 'Usage: simplicio <command>\n  simplicio savings report --json\n  simplicio doctor --json\n'
  })
  assert.equal(ok, true)
})

test('probeSimplicioBin rejects an impostor whose --help has no savings commands (hermes agent shim)', () => {
  const ok = probeSimplicioBin('C:\\fake\\shim-b\\simplicio.cmd', {
    execFileSyncFn: () => 'usage: hermes [-h] [--version] [-z PROMPT] [-m MODEL]\n'
  })
  assert.equal(ok, false)
})

test('probeSimplicioBin rejects a candidate that throws (broken pip launcher stub)', () => {
  const ok = probeSimplicioBin('C:\\fake\\stub-c\\simplicio.exe', {
    execFileSyncFn: () => {
      throw new Error('exit 1: download failed')
    }
  })
  assert.equal(ok, false)
})

test('probeSimplicioBin caches per path (second call does not re-exec)', () => {
  let calls = 0
  const binPath = 'C:\\fake\\cached-d\\simplicio.exe'
  const execFileSyncFn = () => {
    calls += 1
    return 'simplicio savings report'
  }
  assert.equal(probeSimplicioBin(binPath, { execFileSyncFn }), true)
  assert.equal(probeSimplicioBin(binPath, { execFileSyncFn }), true)
  assert.equal(calls, 1)
})

test('isCmdShim flags .cmd/.bat (any case), not .exe or bare names', () => {
  assert.equal(isCmdShim('C:\\bin\\simplicio.cmd'), true)
  assert.equal(isCmdShim('C:\\bin\\SIMPLICIO.CMD'), true)
  assert.equal(isCmdShim('C:\\bin\\simplicio.bat'), true)
  assert.equal(isCmdShim('C:\\bin\\simplicio.exe'), false)
  assert.equal(isCmdShim('/usr/bin/simplicio'), false)
})

test('buildSpawnInvocation wraps a .cmd shim in cmd.exe /d /s /c with args preserved', () => {
  const bin = 'C:\\Users\\u\\.local\\bin\\simplicio.cmd'
  const invocation = buildSpawnInvocation(bin, ['savings', 'report', '--json'], {
    platform: 'win32',
    env: {}
  })
  assert.equal(invocation.command, 'cmd.exe')
  assert.deepEqual(invocation.args, ['/d', '/s', '/c', `"${bin} savings report --json"`])
  assert.equal(invocation.windowsVerbatimArguments, true)
})

test('buildSpawnInvocation quotes shim paths and args containing spaces', () => {
  const bin = 'C:\\Program Files\\Simplicio\\simplicio.cmd'
  const invocation = buildSpawnInvocation(bin, ['memory', 'my query'], {
    platform: 'win32',
    env: {}
  })
  assert.equal(invocation.command, 'cmd.exe')
  assert.deepEqual(invocation.args, ['/d', '/s', '/c', `""${bin}" memory "my query""`])
  assert.equal(invocation.windowsVerbatimArguments, true)
})

test('buildSpawnInvocation honors the comspec env var for the shell path', () => {
  const invocation = buildSpawnInvocation('C:\\bin\\simplicio.cmd', ['doctor'], {
    platform: 'win32',
    env: { comspec: 'C:\\Windows\\System32\\cmd.exe' }
  })
  assert.equal(invocation.command, 'C:\\Windows\\System32\\cmd.exe')
})

test('buildSpawnInvocation passes a real .exe (and any POSIX binary) straight through', () => {
  const exe = buildSpawnInvocation('C:\\bin\\simplicio.exe', ['doctor', '--json'], { platform: 'win32', env: {} })
  assert.deepEqual(exe, {
    command: 'C:\\bin\\simplicio.exe',
    args: ['doctor', '--json'],
    windowsVerbatimArguments: false
  })

  const posix = buildSpawnInvocation('/usr/bin/simplicio', ['doctor'], { platform: 'linux', env: {} })
  assert.deepEqual(posix, { command: '/usr/bin/simplicio', args: ['doctor'], windowsVerbatimArguments: false })
})

test('buildSpawnInvocation does NOT wrap a .cmd path off Windows', () => {
  const invocation = buildSpawnInvocation('/weird/simplicio.cmd', ['doctor'], { platform: 'linux', env: {} })
  assert.deepEqual(invocation, { command: '/weird/simplicio.cmd', args: ['doctor'], windowsVerbatimArguments: false })
})

test('runSimplicio routes a .cmd shim through the cmd.exe wrapper', async () => {
  const bin = 'C:\\Users\\u\\.local\\bin\\simplicio.cmd'
  let seen = null
  const spawnFn = (command, args, options) => {
    seen = { command, args, windowsVerbatimArguments: options.windowsVerbatimArguments }
    const child = new EventEmitter()
    child.stdout = new EventEmitter()
    child.stderr = new EventEmitter()
    child.kill = () => {}
    setImmediate(() => child.emit('exit', 0, null))
    return child
  }
  const result = await runSimplicio(['savings', 'report', '--json'], {
    resolved: { bin, source: 'local-bin' },
    platform: 'win32',
    env: {},
    spawnFn
  })
  assert.equal(result.ok, true)
  assert.equal(seen.command, 'cmd.exe')
  assert.deepEqual(seen.args, ['/d', '/s', '/c', `"${bin} savings report --json"`])
  assert.equal(seen.windowsVerbatimArguments, true)
})

test('parseSimplicioJsonOutput filters progress lines before a trailing single-line JSON object', () => {
  const stdout = [
    '{"schema":"simplicio.progress/v1","step":1}',
    '{"schema":"simplicio.progress/v1","step":2}',
    '{"total_saved":123,"pct":50}'
  ].join('\n')
  assert.deepEqual(parseSimplicioJsonOutput(stdout), { total_saved: 123, pct: 50 })
})

test('parseSimplicioJsonOutput filters progress lines before a pretty-printed multi-line JSON object', () => {
  const stdout = [
    '{"schema":"simplicio.progress/v1","step":1}',
    '{',
    '  "runtime": "simplicio",',
    '  "overall_status": "ok"',
    '}'
  ].join('\n')
  assert.deepEqual(parseSimplicioJsonOutput(stdout), { runtime: 'simplicio', overall_status: 'ok' })
})

test('parseSimplicioJsonOutput handles stdout with no progress lines at all', () => {
  const stdout = '{"a":1}'
  assert.deepEqual(parseSimplicioJsonOutput(stdout), { a: 1 })
})

test('parseSimplicioJsonOutput returns null for empty or non-JSON stdout', () => {
  assert.equal(parseSimplicioJsonOutput(''), null)
  assert.equal(parseSimplicioJsonOutput('not json at all'), null)
})
