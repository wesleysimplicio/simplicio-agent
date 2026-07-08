import { useEffect, useState } from 'react'

import { formatExactTokens, formatPct, formatTokens, formatUsd } from '@/app/savings/format'
import { useLiveDashboard } from '@/app/savings/use-live-dashboard'
import { PanelEmpty } from '@/app/overlays/panel'
import { LiveBadge } from '@/components/savings/live-badge'
import { LiveCounter } from '@/components/savings/live-counter'
import { LiveFeed } from '@/components/savings/live-feed'
import { LiveHeartbeatChart } from '@/components/savings/live-heartbeat-chart'
import { MiniBarList } from '@/components/savings/mini-bar-list'
import { Button } from '@/components/ui/button'
import { useI18n } from '@/i18n'
import { Activity, Loader2 } from '@/lib/icons'

// "Live Activity": the desktop-native mirror of the runtime web dashboard
// (`simplicio dashboard`) — a richer, real-time aggregation than the
// Token Economy report above it (per-provider/per-repo breakdowns, a
// timeseries heartbeat, and an individual-event feed), polled every 3s via
// `useLiveDashboard`. Every number here traces back to a real bridge
// response; an empty/unavailable/erroring backend renders its own honest
// state rather than a fabricated pulse.
export function LiveActivity() {
  const { t } = useI18n()
  const s = t.savings.live
  const { retry, starting, state } = useLiveDashboard()

  // A running counter, not the per-poll boolean: increments once per
  // genuinely-new generation of data so `LiveBadge` can key a one-shot ring
  // per arrival instead of replaying on every unrelated re-render.
  const [pulseKey, setPulseKey] = useState(0)

  useEffect(() => {
    if (state.status === 'ok' && state.diff.isNewGeneration) {
      setPulseKey(key => key + 1)
    }
  }, [state])

  const body = (() => {
    if (state.status === 'unavailable') {
      return <PanelEmpty description={s.unavailableDesc} icon="warning" title={s.unavailableTitle} />
    }

    if (state.status === 'error') {
      return (
        <PanelEmpty
          action={
            <Button disabled={starting} onClick={retry} size="xs" variant="text">
              {starting ? s.retrying : s.retry}
            </Button>
          }
          description={state.error}
          icon="warning"
          title={s.errorTitle}
        />
      )
    }

    if (state.status === 'starting') {
      return (
        <div className="flex items-center gap-2 rounded-lg border border-(--ui-stroke-tertiary) bg-(--ui-bg-tertiary) px-3.5 py-3 text-xs text-muted-foreground/80">
          <Loader2 aria-hidden="true" className="size-3.5 shrink-0 animate-spin" />
          <div>
            <div className="font-medium text-foreground/85">{s.startingTitle}</div>
            <div className="mt-0.5 text-[0.68rem] text-muted-foreground/65">{s.startingDesc}</div>
          </div>
        </div>
      )
    }

    if (state.status === 'loading') {
      return (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          {[0, 1, 2, 3].map(i => (
            <span
              aria-hidden="true"
              className="block h-14 animate-pulse rounded-lg bg-foreground/5"
              key={i}
              style={{ animationDelay: `${i * 80}ms` }}
            />
          ))}
        </div>
      )
    }

    const { summary } = state
    const hasAnyData =
      summary.totals.events !== null ||
      summary.totals.saved !== null ||
      summary.totals.spent !== null ||
      summary.recent.length > 0 ||
      summary.byProvider.length > 0 ||
      summary.byRepo.length > 0 ||
      summary.timeseries.length > 0

    if (!hasAnyData) {
      return <PanelEmpty description={s.emptyDesc} icon="inbox" title={s.emptyTitle} />
    }

    return (
      <div className="grid gap-3">
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <LiveCounter format={formatExactTokens} label={s.eventsLabel} value={summary.totals.events} />
          <LiveCounter format={formatTokens} label={s.savedLabel} value={summary.totals.saved} />
          <LiveCounter format={formatPct} label={s.savedPctLabel} value={summary.totals.savedPct} />
          <LiveCounter format={formatUsd} label={s.costSavedLabel} value={summary.totals.costSavedUsd} />
        </div>

        {summary.timeseries.length >= 2 && (
          <div>
            <div className="mb-1 text-[0.6rem] font-medium uppercase tracking-[0.08em] text-muted-foreground/60">
              {s.timeseriesTitle}
            </div>
            <LiveHeartbeatChart points={summary.timeseries} />
          </div>
        )}

        {(summary.byProvider.length > 0 || summary.byRepo.length > 0) && (
          <div className="grid gap-3 sm:grid-cols-2">
            <MiniBarList slices={summary.byProvider} title={s.byProviderTitle} />
            <MiniBarList slices={summary.byRepo} title={s.byRepoTitle} />
          </div>
        )}

        <div>
          <div className="mb-1 text-[0.6rem] font-medium uppercase tracking-[0.08em] text-muted-foreground/60">
            {s.recentTitle}
          </div>
          <LiveFeed events={summary.recent} newKeys={state.diff.newRecentKeys} />
        </div>
      </div>
    )
  })()

  return (
    <section className="savings-stagger-in" style={{ animationDelay: '380ms' }}>
      <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-1.5 text-[0.625rem] font-medium uppercase tracking-[0.08em] text-muted-foreground/60">
          <Activity className="size-3" />
          {s.title}
        </div>
        {state.status === 'ok' && <LiveBadge pulseKey={pulseKey} updatedAtMs={state.updatedAtMs} />}
      </div>
      <p className="mb-3 text-xs text-muted-foreground/70">{s.subtitle}</p>
      {body}
    </section>
  )
}
