import type { DashboardRecentEvent } from '@/app/savings/dashboard-parse'
import { formatExactTokens, formatTimestamp } from '@/app/savings/format'
import { useI18n } from '@/i18n'
import { cn } from '@/lib/utils'

// The "each session tells what it did, command by command" feed. Newest 8
// entries (the backend already returns `recent` newest-first). An entry
// whose content key is in `newKeys` (see `dashboard-diff.ts`) is one that
// just arrived this poll — it gets a slide-in + a ~1s fading glow border;
// everything else renders statically, exactly as it did last render, so the
// list doesn't jitter on every 3s poll.

const UNKNOWN = '—'

interface LiveFeedProps {
  events: readonly DashboardRecentEvent[]
  newKeys: ReadonlySet<string>
}

export function LiveFeed({ events, newKeys }: LiveFeedProps) {
  const { t } = useI18n()
  const s = t.savings.live

  if (events.length === 0) {
    return <p className="text-[0.66rem] text-muted-foreground/60">{s.recentEmpty}</p>
  }

  return (
    <ul className="grid gap-1">
      {events.slice(0, 8).map(event => {
        const isNew = newKeys.has(event.key)
        const meta = [event.provider, event.model].filter(Boolean).join(' · ')

        return (
          <li
            className={cn(
              'rounded-md border border-(--ui-stroke-tertiary)/70 px-2.5 py-1.5',
              isNew && 'savings-feed-slide-in savings-feed-glow'
            )}
            key={event.key}
          >
            <div className="flex items-center justify-between gap-2">
              <span className="truncate text-[0.7rem] text-foreground/90">{event.task ?? UNKNOWN}</span>
              <span className="shrink-0 text-[0.6rem] tabular-nums text-muted-foreground/60">
                {formatTimestamp(event.ts)}
              </span>
            </div>
            <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[0.62rem] text-muted-foreground/70">
              {meta && <span className="font-mono">{meta}</span>}
              {event.repo && (
                <span className="max-w-32 truncate" title={event.repo}>
                  {event.repo}
                </span>
              )}
              <span className="ml-auto shrink-0 font-medium tabular-nums text-emerald-500 dark:text-emerald-400">
                {s.recentSpentToSaved(formatExactTokens(event.spent), formatExactTokens(event.saved))}
              </span>
            </div>
          </li>
        )
      })}
    </ul>
  )
}
