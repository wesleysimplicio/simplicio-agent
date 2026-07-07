import { useMemo } from 'react'

import { Panel, PanelEmpty } from '@/app/overlays/panel'
import { formatExactTokens, formatPct, formatTokens } from '@/app/savings/format'
import { cumulativeSavedSeries } from '@/app/savings/parse'
import { useSavingsData } from '@/app/savings/use-savings-data'
import { PageLoader } from '@/components/page-loader'
import { HeroStat } from '@/components/savings/hero-stat'
import { McpStatusChip } from '@/components/savings/mcp-status-chip'
import { SavingsChart } from '@/components/savings/savings-chart'
import { SessionEventsTable } from '@/components/savings/session-events-table'
import { Button } from '@/components/ui/button'
import { useI18n } from '@/i18n'
import { RefreshCw } from '@/lib/icons'
import { cn } from '@/lib/utils'

interface TokenMonitorProps {
  onClose: () => void
}

// Vite serves public/ at the base URL (same pattern as brand-mark.tsx).
const assetPath = (path: string) => `${import.meta.env.BASE_URL}${path.replace(/^\/+/, '')}`

// Real, evidenced token-economy panel — replaces the previous Math.random()
// mock. Backed by `window.simplicioSavings` (savings ledger + MCP daemon
// status), never fabricates a figure: every unknown field renders as "—",
// and every reported number carries its measured/estimated proof-kind badge.
export default function TokenMonitor({ onClose }: TokenMonitorProps) {
  const { t } = useI18n()
  const s = t.savings
  const { mcpStatus, refresh, refreshing, state } = useSavingsData()

  const parsed = state.status === 'ok' ? state.parsed : null
  const series = useMemo(() => (parsed ? cumulativeSavedSeries(parsed.events) : []), [parsed])
  const hasAnyData = parsed !== null && (parsed.events.length > 0 || parsed.totals.spent !== null || parsed.totals.baseline !== null)

  return (
    <Panel className="savings-panel" closeLabel={s.close} onClose={onClose}>
      <header className="mb-4 flex shrink-0 items-center gap-3">
        {/* Simplicio brand mark (green hexagonal "S") — cropped from the
            canonical site logo. Not BrandMark: that renders the old Hermes art. */}
        <img
          alt="Simplicio"
          className="size-9 shrink-0 rounded-md object-contain"
          src={assetPath('simplicio-logo.png')}
        />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-sm font-semibold text-foreground">{s.title}</h2>
            <McpStatusChip status={mcpStatus} />
          </div>
          <p className="mt-0.5 truncate text-xs text-muted-foreground/80">{s.subtitle}</p>
        </div>
        <Button
          disabled={refreshing}
          onClick={() => refresh()}
          size="xs"
          title={refreshing ? s.refreshing : s.refresh}
          variant="outline"
        >
          <RefreshCw className={cn('size-3.5', refreshing && 'animate-spin')} />
          {refreshing ? s.refreshing : s.refresh}
        </Button>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto pb-4">
        {state.status === 'unavailable' ? (
          <PanelEmpty description={s.backendUnavailableDesc} icon="warning" title={s.backendUnavailableTitle} />
        ) : state.status === 'error' ? (
          <PanelEmpty
            action={
              <Button onClick={() => refresh()} size="xs" variant="text">
                {s.retry}
              </Button>
            }
            description={state.error}
            icon="warning"
            title={s.errorTitle}
          />
        ) : state.status === 'loading' ? (
          <PageLoader className="min-h-64" label={s.loading} />
        ) : !hasAnyData ? (
          <PanelEmpty description={s.emptyDesc} icon="inbox" title={s.emptyTitle} />
        ) : (
          <div className="grid gap-6">
            <section className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              <HeroStat
                format={formatTokens}
                glow
                label={s.heroTotalSavedLabel}
                staggerMs={0}
                value={parsed.totals.saved}
              />
              <HeroStat format={formatPct} label={s.heroPctSavedLabel} staggerMs={60} value={parsed.totals.pct} />
              <HeroStat
                format={formatTokens}
                hint={parsed.totals.baseline !== null ? s.heroSpentHint(formatTokens(parsed.totals.baseline)) : undefined}
                label={s.heroSpentLabel}
                staggerMs={120}
                value={parsed.totals.spent}
              />
            </section>

            {series.length >= 2 && (
              <section className="savings-stagger-in" style={{ animationDelay: '160ms' }}>
                <div className="mb-2 text-[0.625rem] font-medium uppercase tracking-[0.08em] text-muted-foreground/60">
                  {s.chartTitle}
                </div>
                <SavingsChart points={series} />
              </section>
            )}

            <section className="savings-stagger-in" style={{ animationDelay: '200ms' }}>
              <div className="mb-1 text-[0.625rem] font-medium uppercase tracking-[0.08em] text-muted-foreground/60">
                {s.evidenceSectionTitle}
              </div>
              <p className="mb-3 text-xs text-muted-foreground/70">{s.evidenceSectionDesc}</p>

              <div className="mb-3 flex items-baseline justify-between gap-2">
                <span className="text-[0.7rem] font-medium text-foreground/85">{s.perSessionTitle}</span>
                <span className="text-[0.65rem] tabular-nums text-muted-foreground/60">
                  {formatExactTokens(parsed.events.length)}
                </span>
              </div>

              {!parsed.hasSessionGranularity && parsed.events.length > 0 && (
                <p className="mb-2 text-[0.68rem] text-muted-foreground/60">{s.perSessionAggregatedNote}</p>
              )}

              {parsed.events.length === 0 ? (
                <PanelEmpty description={s.noEventListDesc} icon="inbox" />
              ) : (
                <SessionEventsTable events={parsed.events} />
              )}
            </section>
          </div>
        )}
      </div>
    </Panel>
  )
}
