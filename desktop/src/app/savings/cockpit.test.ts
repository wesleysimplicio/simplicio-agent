import { describe, expect, it } from 'vitest'

import {
  eventTimeLabel,
  guardianTone,
  INITIAL_THRESHOLD_STATE,
  llmHealthy,
  nextThresholdState,
  parseDoctor,
  parseMemoryStatus,
  parseSessions,
  truncateHash
} from './cockpit'

describe('parseMemoryStatus + guardian chips', () => {
  it('maps the documented memory-status payload including the 3 guardians', () => {
    const info = parseMemoryStatus({
      backend_order: ['sqlite-fts5', 'vector'],
      database: '/home/u/.simplicio/memory/simplicio-memory.sqlite',
      guardian_policy: {
        guardians: [
          { decisions: [{ reason: 'r', severity: 'low' }], name: 'Isa', role: 'recall', status: 'active' },
          { decisions: [], name: 'Helo', role: 'context', status: 'idle' },
          { decisions: [], name: 'Levi', role: 'external', status: 'armed' }
        ]
      },
      operator_visibility: { memory: { memory_items: 1304 } },
      selected_backend: 'sqlite-fts5',
      status: 'ready'
    })

    expect(info.status).toBe('ready')
    expect(info.backend).toBe('sqlite-fts5')
    expect(info.memoryItems).toBe(1304)
    expect(info.guardians.map(g => [g.name, g.status, g.decisions])).toEqual([
      ['Isa', 'active', 1],
      ['Helo', 'idle', 0],
      ['Levi', 'armed', 0]
    ])
  })

  it('maps guardian status to chip tones: active=good, idle=info, armed=warn, unknown=muted', () => {
    expect(guardianTone('active')).toBe('good')
    expect(guardianTone('idle')).toBe('info')
    expect(guardianTone('armed')).toBe('warn')
    expect(guardianTone(null)).toBe('muted')
  })

  it('drops malformed guardians and never invents fields', () => {
    const info = parseMemoryStatus({
      guardian_policy: { guardians: ['garbage', { role: 'x' }, { name: 'Isa', status: 'exploded' }] }
    })

    expect(info.guardians).toEqual([{ decisions: 0, name: 'Isa', role: null, status: null }])
    expect(info.memoryItems).toBeNull()
    expect(info.status).toBeNull()
  })

  it('returns all-null info for a non-object payload', () => {
    expect(parseMemoryStatus('nope').guardians).toEqual([])
    expect(parseMemoryStatus(null).memoryItems).toBeNull()
  })
})

describe('parseDoctor + llmHealthy', () => {
  it('extracts version, overall status, binary, and model policy', () => {
    const info = parseDoctor({
      execution: { binary: '/usr/local/bin/simplicio' },
      overall_status: 'ok',
      policy: { local: true, model: 'gemma4:4b-q4_K_M', offline_first: true },
      version: '3.4.0'
    })

    expect(info).toEqual({
      binary: '/usr/local/bin/simplicio',
      local: true,
      model: 'gemma4:4b-q4_K_M',
      offlineFirst: true,
      overallStatus: 'ok',
      version: '3.4.0'
    })
    expect(llmHealthy(info)).toBe(true)
  })

  it('is healthy on warning with a model, unhealthy without a model or on error', () => {
    expect(llmHealthy(parseDoctor({ overall_status: 'warning', policy: { model: 'm' } }))).toBe(true)
    expect(llmHealthy(parseDoctor({ overall_status: 'ok', policy: {} }))).toBe(false)
    expect(llmHealthy(parseDoctor({ overall_status: 'error', policy: { model: 'm' } }))).toBe(false)
  })
})

describe('parseSessions (audit timeline)', () => {
  const rawSession = {
    branch: 'main',
    endedAt: '2026-07-07T12:30:00Z',
    events: [
      {
        eventHash: 'abcdef0123456789',
        eventId: 'e1',
        model: 'gemma4',
        prevEventHash: '9876543210fedcba',
        proofKind: 'measured',
        provider: 'local',
        surfaces: ['runtime_map', 'memory', 'edit'],
        taskTitle: 'Fix parser',
        timestamp: '2026-07-07T12:00:00Z',
        tokens: { baseline: 1000, saved: 900, spent: 100 }
      }
    ],
    repo: '/repo/x',
    runId: 'run-1',
    startedAt: '2026-07-07T12:00:00Z',
    title: 'Parser session',
    totals: { baseline: 1000, saved: 900, spent: 100 }
  }

  it('normalizes the main-process session shape, computing savedPct from real totals', () => {
    const [session] = parseSessions([rawSession])

    expect(session.runId).toBe('run-1')
    expect(session.savedPct).toBe(90)
    expect(session.events[0].surfaces).toEqual(['runtime_map', 'memory', 'edit'])
    expect(session.events[0].proofKind).toBe('measured')
    expect(session.events[0].eventHash).toBe('abcdef0123456789')
  })

  it('defaults the honesty-state fields when the ledger event carries none of them', () => {
    const [session] = parseSessions([rawSession])
    const [event] = session.events

    expect(event.sessionId).toBeNull()
    expect(event.cache).toBeNull()
    expect(event.cost).toBeNull()
    expect(event.latencyMs).toBeNull()
    expect(event.tools).toEqual([])
    expect(event.evidenceRefs).toEqual([])
    // No hash-state carried -> honest "nothing was checked" default.
    expect(event.hashState).toBe('unverified')
    // No token figures on this raw fixture's tokens shape carries values ->
    // priceState reflects whatever is actually present.
    expect(event.priceState).toBe('not_applicable')
  })

  it('parses the extended cockpit event fields (issue #128) when the main process supplies them', () => {
    const [session] = parseSessions([
      {
        ...rawSession,
        events: [
          {
            ...rawSession.events[0],
            cache: { hit: true, readTokens: 120, writeTokens: 0 },
            cost: 0.0042,
            evidenceRefs: ['transcript://abc123'],
            hashState: 'invalid',
            latencyMs: 842,
            priceState: 'priced',
            sessionId: 'sess-1',
            tools: ['edit', 'bash']
          }
        ]
      }
    ])
    const [event] = session.events

    expect(event.sessionId).toBe('sess-1')
    expect(event.cache).toEqual({ hit: true, readTokens: 120, writeTokens: 0 })
    expect(event.cost).toBe(0.0042)
    expect(event.latencyMs).toBe(842)
    expect(event.tools).toEqual(['edit', 'bash'])
    expect(event.evidenceRefs).toEqual(['transcript://abc123'])
    expect(event.hashState).toBe('invalid')
    expect(event.priceState).toBe('priced')
  })

  it('falls back to raw ledger snake_case field names for the extended fields', () => {
    const [session] = parseSessions([
      {
        ...rawSession,
        events: [
          {
            ...rawSession.events[0],
            cost_usd: 1.5,
            evidence_refs: ['ref-a'],
            hash_state: 'valid',
            latency_ms: 100,
            price_state: 'missing_price',
            session_id: 'raw-sess',
            tools: ['grep']
          }
        ]
      }
    ])
    const [event] = session.events

    expect(event.sessionId).toBe('raw-sess')
    expect(event.cost).toBe(1.5)
    expect(event.latencyMs).toBe(100)
    expect(event.evidenceRefs).toEqual(['ref-a'])
    expect(event.hashState).toBe('valid')
    expect(event.priceState).toBe('missing_price')
  })

  it('never invents a hashState/priceState value outside the known set', () => {
    const [session] = parseSessions([
      {
        ...rawSession,
        events: [{ ...rawSession.events[0], hashState: 'exploded', priceState: 'nonsense' }]
      }
    ])
    const [event] = session.events

    expect(event.hashState).toBe('unverified')
    expect(event.priceState).toBe('not_applicable')
  })

  it('also accepts raw ledger token field names (actual_total/baseline_total/saved_total)', () => {
    const [session] = parseSessions([
      {
        events: [{ tokens: { actual_total: 10, baseline_total: 40, saved_total: 30 } }],
        run_id: 'raw',
        totals: { actual_total: 10, baseline_total: 40, saved_total: 30 }
      }
    ])

    expect(session.totals).toEqual({ baseline: 40, saved: 30, spent: 10 })
    expect(session.events[0].tokens.saved).toBe(30)
    expect(session.savedPct).toBe(75)
  })

  it('never invents savedPct without both figures, and tolerates garbage entries', () => {
    const sessions = parseSessions(['junk', { runId: 'r2', totals: { saved: 5 } }])

    expect(sessions).toHaveLength(1)
    expect(sessions[0].savedPct).toBeNull()
    expect(sessions[0].events).toEqual([])
  })

  it('returns [] for a non-array payload', () => {
    expect(parseSessions({ not: 'an array' })).toEqual([])
  })
})

describe('timeline formatters', () => {
  it('truncates hashes to 8 chars for the chip, null-tolerant', () => {
    expect(truncateHash('abcdef0123456789')).toBe('abcdef01')
    expect(truncateHash('abc')).toBe('abc')
    expect(truncateHash(null)).toBeNull()
  })

  it('falls back to the raw string for an unparseable timestamp and null for none', () => {
    expect(eventTimeLabel('not-a-date')).toBe('not-a-date')
    expect(eventTimeLabel(null)).toBeNull()
    expect(eventTimeLabel('2026-07-07T12:00:00Z')).toMatch(/\d{1,2}:\d{2}/)
  })
})

describe('nextThresholdState (Neon Burst trigger)', () => {
  it('fires exactly once when crossing up, and not while staying above', () => {
    const crossed = nextThresholdState(INITIAL_THRESHOLD_STATE, 95, 90)

    expect(crossed).toEqual({ active: true, burstCount: 1 })
    // Staying above: same state object, no new burst.
    expect(nextThresholdState(crossed, 97, 90)).toBe(crossed)
    expect(nextThresholdState(crossed, 100, 90)).toBe(crossed)
  })

  it('re-arms after dropping below and fires again on the next crossing', () => {
    const up = nextThresholdState(INITIAL_THRESHOLD_STATE, 92, 90)
    const down = nextThresholdState(up, 80, 90)

    expect(down).toEqual({ active: false, burstCount: 1 })

    const upAgain = nextThresholdState(down, 91, 90)

    expect(upAgain).toEqual({ active: true, burstCount: 2 })
  })

  it('treats null as below threshold and exactly-90 as above', () => {
    expect(nextThresholdState(INITIAL_THRESHOLD_STATE, null, 90)).toBe(INITIAL_THRESHOLD_STATE)
    expect(nextThresholdState(INITIAL_THRESHOLD_STATE, 90, 90).active).toBe(true)
  })
})
