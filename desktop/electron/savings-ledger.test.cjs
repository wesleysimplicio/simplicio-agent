'use strict'

const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')

const {
  parseSavingsLedger,
  dedupByEventId,
  groupSavingsSessions,
  readSavingsSessions,
  hashStateOf,
  priceStateOf
} = require('./savings-ledger.cjs')

// Build a realistic v1 ledger event (shape verified against the machine's
// real ~/.simplicio/ledger/savings-events.jsonl on 2026-07-07).
function makeEvent(overrides = {}) {
  return {
    schema: 'simplicio.savings-event/v1',
    event_id: 'ev-default',
    simplicio: { surfaces: ['runtime_map', 'memory'], run_id: 'run-default' },
    timestamp: '2026-07-07T22:52:44Z',
    prev_event_hash: null,
    event_hash: 'hash-default',
    repo: { path: 'C:\\repo', branch: 'main', commit: 'abc' },
    task: { id: 'task-1', source: 'simplicio-cli', title: 'memory' },
    llm: { provider: 'simplicio', model: 'simplicio-cli' },
    tokens: { actual_total: 0, baseline_total: 2000, saved_total: 2000 },
    proof: { kind: 'estimated' },
    ...overrides
  }
}

test('parseSavingsLedger keeps valid object lines and counts corrupted ones as skipped', () => {
  const text = [
    JSON.stringify(makeEvent({ event_id: 'a' })),
    '{broken json line',
    '', // blank lines are ignored, not skipped
    JSON.stringify(makeEvent({ event_id: 'b' })),
    '"just a string, not an object"',
    '[1,2,3]'
  ].join('\n')
  const { events, skipped } = parseSavingsLedger(text)
  assert.equal(events.length, 2)
  assert.equal(skipped, 3)
  assert.deepEqual(
    events.map(e => e.event_id),
    ['a', 'b']
  )
})

test('dedupByEventId drops duplicate event_ids across merged files, keeps id-less events', () => {
  const events = [
    makeEvent({ event_id: 'dup' }),
    makeEvent({ event_id: 'dup' }),
    makeEvent({ event_id: 'unique' }),
    { schema: 'simplicio.savings-event/v1' }, // no event_id -> kept
    { schema: 'simplicio.savings-event/v1' } // no event_id -> also kept
  ]
  const out = dedupByEventId(events)
  assert.equal(out.length, 4)
  assert.equal(out.filter(e => e.event_id === 'dup').length, 1)
})

test('groupSavingsSessions groups interleaved events of 2 runs, sorts events asc and sessions by endedAt desc', () => {
  const events = [
    makeEvent({
      event_id: 'b2',
      simplicio: { surfaces: ['edit'], run_id: 'run-b' },
      timestamp: '2026-07-07T12:30:00Z',
      tokens: { actual_total: 10, baseline_total: 100, saved_total: 90 }
    }),
    makeEvent({
      event_id: 'a1',
      simplicio: { surfaces: ['memory'], run_id: 'run-a' },
      timestamp: '2026-07-07T10:00:00Z',
      task: { id: 't-a', title: 'first task of run a' },
      tokens: { actual_total: 5, baseline_total: 50, saved_total: 45 }
    }),
    makeEvent({
      event_id: 'b1',
      simplicio: { surfaces: ['runtime_map'], run_id: 'run-b' },
      timestamp: '2026-07-07T12:00:00Z',
      task: { id: 't-b', title: 'first task of run b' },
      tokens: { actual_total: 20, baseline_total: 200, saved_total: 180 }
    }),
    makeEvent({
      event_id: 'a2',
      simplicio: { surfaces: ['validate'], run_id: 'run-a' },
      timestamp: '2026-07-07T11:00:00Z',
      tokens: { actual_total: 15, baseline_total: 150, saved_total: 135 }
    })
  ]

  const sessions = groupSavingsSessions(events)
  assert.equal(sessions.length, 2)

  // run-b ended latest (12:30) -> first.
  assert.equal(sessions[0].runId, 'run-b')
  assert.equal(sessions[1].runId, 'run-a')

  const runB = sessions[0]
  assert.deepEqual(
    runB.events.map(e => e.eventId),
    ['b1', 'b2'],
    'events inside a session are timestamp-ascending'
  )
  assert.equal(runB.title, 'first task of run b')
  assert.equal(runB.startedAt, '2026-07-07T12:00:00Z')
  assert.equal(runB.endedAt, '2026-07-07T12:30:00Z')
  assert.deepEqual(runB.totals, { spent: 30, baseline: 300, saved: 270 })

  const runA = sessions[1]
  assert.deepEqual(runA.totals, { spent: 20, baseline: 200, saved: 180 })
  assert.equal(runA.events[0].surfaces[0], 'memory')
  assert.equal(runA.events[0].proofKind, 'estimated')
  assert.equal(runA.events[0].model, 'simplicio-cli')
  assert.equal(runA.events[0].provider, 'simplicio')
})

test('groupSavingsSessions falls back to task.id then "unknown" for the run id', () => {
  const sessions = groupSavingsSessions([
    makeEvent({ event_id: 'x', simplicio: { surfaces: [] }, task: { id: 'task-as-run', title: 't' } }),
    makeEvent({ event_id: 'y', simplicio: {}, task: {} })
  ])
  const runIds = sessions.map(s => s.runId).sort()
  assert.deepEqual(runIds, ['task-as-run', 'unknown'])
})

test('groupSavingsSessions reports null (never invented) for absent fields and totals', () => {
  const sessions = groupSavingsSessions([{ event_id: 'bare', simplicio: { run_id: 'r' } }])
  assert.equal(sessions.length, 1)
  const s = sessions[0]
  assert.equal(s.title, null)
  assert.equal(s.repo, null)
  assert.equal(s.branch, null)
  assert.equal(s.startedAt, null)
  assert.equal(s.endedAt, null)
  assert.deepEqual(s.totals, { spent: null, baseline: null, saved: null })
  const e = s.events[0]
  assert.equal(e.timestamp, null)
  assert.equal(e.surfaces, null)
  assert.equal(e.taskTitle, null)
  assert.deepEqual(e.tokens, { spent: null, baseline: null, saved: null })
  assert.equal(e.proofKind, null)
  assert.equal(e.eventHash, null)
  assert.equal(e.prevEventHash, null)
  assert.equal(e.model, null)
  assert.equal(e.provider, null)
  assert.equal(e.sessionId, null)
  assert.equal(e.cache, null)
  assert.equal(e.cost, null)
  assert.equal(e.latencyMs, null)
  assert.equal(e.tools, null)
  assert.equal(e.evidenceRefs, null)
  // No hash at all -> nothing to chain-verify.
  assert.equal(e.hashState, 'unverified')
  // No token figures at all -> pricing never applied.
  assert.equal(e.priceState, 'not_applicable')
})

test('hashStateOf: valid genesis, valid continuity, invalid break, unverified when unhashed', () => {
  const genesis = { eventHash: 'h1', prevEventHash: null }
  assert.equal(hashStateOf(genesis, null), 'valid')

  const linked = { eventHash: 'h2', prevEventHash: 'h1' }
  assert.equal(hashStateOf(linked, genesis), 'valid')

  const broken = { eventHash: 'h3', prevEventHash: 'not-h2' }
  assert.equal(hashStateOf(broken, linked), 'invalid')

  const noLink = { eventHash: 'h4', prevEventHash: null }
  assert.equal(hashStateOf(noLink, broken), 'unverified')

  const unhashed = { eventHash: null, prevEventHash: 'h4' }
  assert.equal(hashStateOf(unhashed, noLink), 'unverified')

  // A non-null prevEventHash on the very first event of a session can't be
  // checked against anything this window has.
  const dangling = { eventHash: 'h1', prevEventHash: 'some-earlier-hash' }
  assert.equal(hashStateOf(dangling, null), 'unverified')
})

test('priceStateOf: priced with a real cost figure, missing_price with tokens but no cost, not_applicable with neither', () => {
  assert.equal(priceStateOf({ actual_total: 10, baseline_total: 20 }, 0.05), 'priced')
  assert.equal(priceStateOf({ actual_total: 10, baseline_total: 20 }, null), 'missing_price')
  assert.equal(priceStateOf({}, null), 'not_applicable')
})

test('groupSavingsSessions marks hashState per event via chain-link continuity within a session', () => {
  const sessions = groupSavingsSessions([
    makeEvent({
      event_id: 'g1',
      simplicio: { run_id: 'run-chain' },
      timestamp: '2026-07-08T10:00:00Z',
      event_hash: 'h1',
      prev_event_hash: null
    }),
    makeEvent({
      event_id: 'g2',
      simplicio: { run_id: 'run-chain' },
      timestamp: '2026-07-08T10:01:00Z',
      event_hash: 'h2',
      prev_event_hash: 'h1'
    }),
    makeEvent({
      event_id: 'g3',
      simplicio: { run_id: 'run-chain' },
      timestamp: '2026-07-08T10:02:00Z',
      event_hash: 'h3',
      prev_event_hash: 'TAMPERED'
    })
  ])
  const [session] = sessions
  assert.deepEqual(
    session.events.map(e => [e.eventId, e.hashState]),
    [
      ['g1', 'valid'],
      ['g2', 'valid'],
      ['g3', 'invalid']
    ]
  )
})

test('readSavingsSessions merges home + repo ledgers, dedups by event_id, counts skipped', () => {
  const home = fs.mkdtempSync(path.join(os.tmpdir(), 'simplicio-ledger-home-'))
  const repo = fs.mkdtempSync(path.join(os.tmpdir(), 'simplicio-ledger-repo-'))
  try {
    const homeLedgerDir = path.join(home, '.simplicio', 'ledger')
    const repoLedgerDir = path.join(repo, '.simplicio', 'ledger')
    fs.mkdirSync(homeLedgerDir, { recursive: true })
    fs.mkdirSync(repoLedgerDir, { recursive: true })

    const shared = makeEvent({ event_id: 'shared', simplicio: { run_id: 'run-1' } })
    const homeOnly = makeEvent({
      event_id: 'home-only',
      simplicio: { run_id: 'run-1' },
      timestamp: '2026-07-07T23:00:00Z'
    })
    const repoOnly = makeEvent({ event_id: 'repo-only', simplicio: { run_id: 'run-2' } })

    fs.writeFileSync(
      path.join(homeLedgerDir, 'savings-events.jsonl'),
      [JSON.stringify(shared), JSON.stringify(homeOnly), 'CORRUPTED {'].join('\n')
    )
    fs.writeFileSync(
      path.join(repoLedgerDir, 'savings-events.jsonl'),
      [JSON.stringify(shared), JSON.stringify(repoOnly)].join('\n')
    )

    const result = readSavingsSessions({ homedir: home, repoPath: repo })
    assert.equal(result.ok, true)
    assert.equal(result.skipped, 1)
    // The `shared` event appears in both files -> 1 duplicate, distinct from
    // the 1 corrupted line counted as `skipped` above.
    assert.equal(result.duplicates, 1)
    assert.equal(result.sources.length, 2)

    const allEventIds = result.sessions.flatMap(s => s.events.map(e => e.eventId)).sort()
    assert.deepEqual(allEventIds, ['home-only', 'repo-only', 'shared'], 'shared event deduped across files')

    const run1 = result.sessions.find(s => s.runId === 'run-1')
    assert.equal(run1.events.length, 2)
  } finally {
    fs.rmSync(home, { recursive: true, force: true })
    fs.rmSync(repo, { recursive: true, force: true })
  }
})

test('readSavingsSessions returns ok:true with zero sessions when no ledger exists (fresh machine)', () => {
  const home = fs.mkdtempSync(path.join(os.tmpdir(), 'simplicio-ledger-empty-'))
  try {
    const result = readSavingsSessions({ homedir: home })
    assert.deepEqual(result, { ok: true, sessions: [], skipped: 0, duplicates: 0, sources: [] })
  } finally {
    fs.rmSync(home, { recursive: true, force: true })
  }
})

test('readSavingsSessions surfaces a non-ENOENT read failure as ok:false with the error', () => {
  const result = readSavingsSessions({
    homedir: '/home/x',
    fsImpl: {
      readFileSync: () => {
        const err = new Error('EACCES: permission denied')
        err.code = 'EACCES'
        throw err
      }
    }
  })
  assert.equal(result.ok, false)
  assert.match(result.error, /EACCES/)
  assert.deepEqual(result.sessions, [])
})
