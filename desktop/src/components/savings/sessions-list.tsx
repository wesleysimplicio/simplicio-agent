import { useState } from 'react'

import { type CockpitEvent, type CockpitSession, eventTimeLabel, truncateHash } from '@/app/savings/cockpit'
import { formatExactTokens, formatTimestamp, formatTokens, formatUsd } from '@/app/savings/format'
import type { ParsedSessions } from '@/app/savings/use-savings-data'
import { NeonBurst } from '@/components/savings/neon-burst'
import { ProofBadge } from '@/components/savings/proof-badge'
import { useThresholdCrossing } from '@/components/savings/use-threshold-crossing'
import { Tip } from '@/components/ui/tooltip'
import { useI18n } from '@/i18n'
import { ChevronDown } from '@/lib/icons'
import { cn } from '@/lib/utils'

// Per-run audit drill-down: each session card expands into a vertical
// timeline of ledger events — what the runtime did at each step (surfaces =
// the runtime commands used), tokens spent vs baseline, proof-kind, and the
// verifiable HBP hash chain (prev → this). The footer lists the ledger files
// the data actually came from — provenance, not decoration.

const UNKNOWN = '—'

function formatCache(cache: CockpitEvent['cache']): string {
  if (!cache) {
    return UNKNOWN
  }

  const hit = cache.hit === null ? UNKNOWN : cache.hit ? 'yes' : 'no'

  return `hit=${hit} read=${formatExactTokens(cache.readTokens)} write=${formatExactTokens(cache.writeTokens)}`
}

function formatList(values: readonly string[]): string {
  return values.length > 0 ? values.join(', ') : UNKNOWN
}

function SavedBadge({ pct, saved }: { pct: null | number; saved: null | number }) {
  const { t } = useI18n()
  const s = t.savings
  const crossing = useThresholdCrossing(pct, 90)

  return (
    <span
      aria-label={crossing.active ? s.cockpit.superSavingsAria : undefined}
      className={cn(
        'relative inline-flex shrink-0 items-center gap-1 rounded-full bg-emerald-500/12 px-2 py-0.5 text-[0.66rem] font-semibold tabular-nums text-emerald-500 dark:text-emerald-400',
        crossing.active && 'savings-super'
      )}
    >
      {formatTokens(saved)}
      {pct !== null && <span className="font-normal opacity-80">({pct}%)</span>}
      {crossing.active && (
        <span className="savings-super-badge items-center rounded-full border border-emerald-500/50 px-1 text-[0.55rem]">
          90%+
        </span>
      )}
      {crossing.active && crossing.burstKey > 0 && <NeonBurst key={crossing.burstKey} mini />}
    </span>
  )
}

function TimelineEvent({ event, isLast }: { event: CockpitEvent; isLast: boolean }) {
  const { t } = useI18n()
  const s = t.savings
  const hash = truncateHash(event.eventHash)
  const prevHash = truncateHash(event.prevEventHash)

  return (
    <li className="relative grid grid-cols-[auto_1fr] gap-x-3">
      <div className="flex flex-col items-center">
        <span aria-hidden="true" className="mt-1.5 size-2 shrink-0 rounded-full border border-emerald-500/60 bg-emerald-500/30" />
        {!isLast && <span aria-hidden="true" className="w-px flex-1 bg-(--ui-stroke-tertiary)" />}
      </div>
      <div className="min-w-0 pb-4">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <span className="text-[0.64rem] tabular-nums text-muted-foreground/70">
            {eventTimeLabel(event.timestamp) ?? UNKNOWN}
          </span>
          {event.surfaces.map(surface => (
            <span
              className="rounded border border-(--ui-stroke-tertiary) bg-(--ui-bg-quinary) px-1 py-px font-mono text-[0.58rem] text-foreground/75"
              key={surface}
            >
              {surface}
            </span>
          ))}
          <ProofBadge proofKind={event.proofKind} />
          {hash && (
            <Tip label={`${s.cockpit.hashChainTooltip}: ${prevHash ?? UNKNOWN} -> ${hash}`}>
              <span className="rounded bg-foreground/6 px-1 py-px font-mono text-[0.58rem] text-muted-foreground/70">
                {hash}
              </span>
            </Tip>
          )}
        </div>
        {event.taskTitle && <div className="mt-1 truncate text-[0.72rem] text-foreground/90">{event.taskTitle}</div>}
        <div className="mt-0.5 flex flex-wrap items-center gap-x-3 text-[0.64rem] tabular-nums text-muted-foreground/70">
          <span>
            {formatExactTokens(event.tokens.spent)} {'->'} {formatExactTokens(event.tokens.baseline)}{' '}
            <span className="font-medium text-emerald-500 dark:text-emerald-400">
              ({s.cockpit.savedShort} {formatExactTokens(event.tokens.saved)})
            </span>
          </span>
          {(event.model || event.provider) && (
            <span className="font-mono text-[0.6rem]">{[event.model, event.provider].filter(Boolean).join(' · ')}</span>
          )}
        </div>
        <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 font-mono text-[0.58rem] text-muted-foreground/60">
          <span>session={event.sessionId ?? UNKNOWN}</span>
          <span>cost={formatUsd(event.cost)}</span>
          <span>cache={formatCache(event.cache)}</span>
          <span>latency={event.latencyMs === null ? UNKNOWN : `${event.latencyMs}ms`}</span>
          <span>tools={formatList(event.tools)}</span>
          <span className="max-w-full truncate" title={formatList(event.evidenceRefs)}>
            evidence={formatList(event.evidenceRefs)}
          </span>
          <span>hash={event.hashState}</span>
          <span>price={event.priceState}</span>
        </div>
      </div>
    </li>
  )
}

function SessionCard({ session, staggerMs }: { session: CockpitSession; staggerMs: number }) {
  const { t } = useI18n()
  const s = t.savings
  const [open, setOpen] = useState(false)

  const period = [formatTimestamp(session.startedAt), formatTimestamp(session.endedAt)]
    .filter(v => v !== UNKNOWN)
    .join(' -> ')

  return (
    <div
      className="savings-stagger-in overflow-hidden rounded-lg border border-(--ui-stroke-tertiary) bg-(--ui-bg-quinary) transition-colors hover:border-(--ui-stroke-secondary)"
      style={{ animationDelay: `${staggerMs}ms` }}
    >
      <button
        aria-expanded={open}
        className="grid w-full grid-cols-[1fr_auto_auto] items-center gap-3 px-3.5 py-2.5 text-left"
        onClick={() => setOpen(value => !value)}
        type="button"
      >
        <span className="min-w-0">
          <span className="block truncate text-[0.76rem] font-medium text-foreground">
            {session.title ?? session.runId}
          </span>
          <span className="mt-0.5 block truncate text-[0.62rem] text-muted-foreground/70">
            {`run=${session.runId} · `}
            {[session.repo, session.branch].filter(Boolean).join(' @ ') || UNKNOWN}
            {period ? ` · ${period}` : ''}
            {` · ${s.cockpit.eventsCount(session.events.length)}`}
          </span>
        </span>
        <SavedBadge pct={session.savedPct} saved={session.totals.saved} />
        <ChevronDown
          className={cn('size-3.5 shrink-0 text-muted-foreground/60 transition-transform duration-200', open && 'rotate-180')}
        />
      </button>

      {open && (
        <div className="border-t border-(--ui-stroke-tertiary) px-3.5 pt-3">
          <ul>
            {session.events.map((event, index) => (
              <TimelineEvent event={event} isLast={index === session.events.length - 1} key={event.id} />
            ))}
          </ul>
          {session.events.length === 0 && (
            <p className="pb-3 text-[0.66rem] text-muted-foreground/60">{s.cockpit.noEvents}</p>
          )}
        </div>
      )}
    </div>
  )
}

export function SessionsList({ data }: { data: ParsedSessions }) {
  const { t } = useI18n()
  const s = t.savings

  return (
    <div className="grid gap-2">
      {data.sessions.map((session, index) => (
        <SessionCard key={session.runId} session={session} staggerMs={Math.min(index, 8) * 40} />
      ))}

      <footer className="mt-1 grid gap-0.5 text-[0.6rem] text-muted-foreground/55">
        {data.sources.map(source => (
          <span className="truncate font-mono" key={source} title={source}>
            {s.cockpit.sourceLabel} {source}
          </span>
        ))}
        {data.skipped > 0 && <span>{s.cockpit.skippedLines(data.skipped)}</span>}
      </footer>
    </div>
  )
}
