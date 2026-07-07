'use strict'

/**
 * savings-ledger.cjs
 *
 * Direct, spawn-free reader for the simplicio savings ledgers -- the
 * append-only JSONL files at `~/.simplicio/ledger/savings-events.jsonl`
 * (home) and `<repo>/.simplicio/ledger/savings-events.jsonl` (per-repo).
 * Each line is one `simplicio.savings-event/v1` event; this module parses
 * them tolerantly (bad line -> skipped, never a throw), dedups by event_id
 * across files, and groups events into per-run "sessions" for the desktop
 * cockpit.
 *
 * HONESTY RULE: a field the event doesn't carry is `null` -- never a guessed
 * or defaulted value. Totals are summed only over numbers that are actually
 * present; a session whose events carry no token figures reports null totals.
 *
 * Pure parsing/grouping is exported separately from the fs-reading wrapper so
 * it unit-tests with plain strings (same DI pattern as the sibling modules).
 */

const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')

/** Finite number or null -- never coerce garbage into a figure. */
function numOrNull(value) {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

/** Non-empty string or null. */
function strOrNull(value) {
  return typeof value === 'string' && value.trim() !== '' ? value : null
}

/** Array of strings or null (surfaces list). */
function stringArrayOrNull(value) {
  if (!Array.isArray(value)) return null
  return value.filter(entry => typeof entry === 'string')
}

/** Epoch ms for an ISO timestamp string, or null when unparseable. */
function timestampMs(value) {
  if (typeof value !== 'string') return null
  const ms = Date.parse(value)
  return Number.isFinite(ms) ? ms : null
}

/**
 * Parse raw JSONL ledger text into `{ events, skipped }`. A line is kept when
 * it parses as a JSON object; anything else (blank lines excluded) counts as
 * skipped. No field validation here -- normalization happens per-event in
 * groupSavingsSessions, where a missing field is null.
 */
function parseSavingsLedger(text) {
  const events = []
  let skipped = 0
  for (const line of String(text || '').split(/\r?\n/)) {
    const trimmed = line.trim()
    if (!trimmed) continue
    try {
      const parsed = JSON.parse(trimmed)
      if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
        events.push(parsed)
      } else {
        skipped += 1
      }
    } catch {
      skipped += 1
    }
  }
  return { events, skipped }
}

/** Dedup raw events by event_id (events without one are all kept). */
function dedupByEventId(events) {
  const seen = new Set()
  const out = []
  for (const event of events) {
    const id = strOrNull(event.event_id)
    if (id) {
      if (seen.has(id)) continue
      seen.add(id)
    }
    out.push(event)
  }
  return out
}

/** Normalize one raw ledger event into the cockpit's event shape. */
function normalizeEvent(raw) {
  const tokens = raw.tokens && typeof raw.tokens === 'object' ? raw.tokens : {}
  return {
    eventId: strOrNull(raw.event_id),
    timestamp: strOrNull(raw.timestamp),
    surfaces: stringArrayOrNull(raw.simplicio && raw.simplicio.surfaces),
    taskTitle: strOrNull(raw.task && raw.task.title),
    tokens: {
      spent: numOrNull(tokens.actual_total),
      baseline: numOrNull(tokens.baseline_total),
      saved: numOrNull(tokens.saved_total)
    },
    proofKind: strOrNull(raw.proof && raw.proof.kind),
    eventHash: strOrNull(raw.event_hash),
    prevEventHash: strOrNull(raw.prev_event_hash),
    model: strOrNull(raw.llm && raw.llm.model),
    provider: strOrNull(raw.llm && raw.llm.provider)
  }
}

/** The run a raw event belongs to: run_id, else task id, else 'unknown'. */
function runIdOf(raw) {
  return strOrNull(raw.simplicio && raw.simplicio.run_id) || strOrNull(raw.task && raw.task.id) || 'unknown'
}

/** Sum only the figures that are actually present; null when none are. */
function sumOrNull(values) {
  let total = null
  for (const value of values) {
    if (value !== null) total = (total ?? 0) + value
  }
  return total
}

/**
 * Group deduped raw events into sessions, one per run id, newest (by
 * endedAt) first. Events inside a session are ordered by timestamp
 * ascending; events with no parseable timestamp sort first, preserving
 * ledger (append) order among themselves.
 */
function groupSavingsSessions(rawEvents) {
  const byRun = new Map()
  for (const raw of rawEvents) {
    const runId = runIdOf(raw)
    if (!byRun.has(runId)) byRun.set(runId, [])
    byRun.get(runId).push(raw)
  }

  const sessions = []
  for (const [runId, group] of byRun) {
    const sorted = [...group].sort((a, b) => (timestampMs(a.timestamp) ?? -Infinity) - (timestampMs(b.timestamp) ?? -Infinity))
    const events = sorted.map(normalizeEvent)
    const first = sorted[0]

    const timestamps = sorted.map(raw => strOrNull(raw.timestamp)).filter(Boolean)
    sessions.push({
      runId,
      title: strOrNull(first.task && first.task.title),
      repo: strOrNull(first.repo && first.repo.path),
      branch: strOrNull(first.repo && first.repo.branch),
      startedAt: timestamps.length ? timestamps[0] : null,
      endedAt: timestamps.length ? timestamps[timestamps.length - 1] : null,
      totals: {
        spent: sumOrNull(events.map(event => event.tokens.spent)),
        baseline: sumOrNull(events.map(event => event.tokens.baseline)),
        saved: sumOrNull(events.map(event => event.tokens.saved))
      },
      events
    })
  }

  sessions.sort((a, b) => (timestampMs(b.endedAt) ?? -Infinity) - (timestampMs(a.endedAt) ?? -Infinity))
  return sessions
}

/**
 * Read + parse + dedup + group the machine's savings ledgers.
 *
 * Sources: the home ledger (`~/.simplicio/ledger/savings-events.jsonl`)
 * always, plus `<repoPath>/.simplicio/ledger/savings-events.jsonl` when
 * `opts.repoPath` is given and the file exists. Missing files are fine (an
 * empty machine reports zero sessions, not an error); only an unexpected
 * read failure returns `{ok:false, error}`. Never throws.
 *
 * `opts.homedir`/`opts.fsImpl` are injectable for tests.
 */
function readSavingsSessions(opts = {}) {
  const fsImpl = opts.fsImpl || fs
  const homedir = opts.homedir || os.homedir()

  const candidates = [path.join(homedir, '.simplicio', 'ledger', 'savings-events.jsonl')]
  const repoPath = strOrNull(opts.repoPath)
  if (repoPath) {
    candidates.push(path.join(repoPath, '.simplicio', 'ledger', 'savings-events.jsonl'))
  }

  const sources = []
  const allEvents = []
  let skipped = 0
  try {
    for (const candidate of candidates) {
      let text
      try {
        text = fsImpl.readFileSync(candidate, 'utf8')
      } catch (error) {
        if (error && error.code === 'ENOENT') continue
        throw error
      }
      sources.push(candidate)
      const { events, skipped: badLines } = parseSavingsLedger(text)
      allEvents.push(...events)
      skipped += badLines
    }
  } catch (error) {
    return { ok: false, sessions: [], skipped, sources, error: error.message }
  }

  const sessions = groupSavingsSessions(dedupByEventId(allEvents))
  return { ok: true, sessions, skipped, sources }
}

module.exports = {
  parseSavingsLedger,
  dedupByEventId,
  groupSavingsSessions,
  readSavingsSessions
}
