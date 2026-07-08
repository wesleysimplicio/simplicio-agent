import { useStore } from '@nanostores/react'
import { useEffect, useMemo, useRef } from 'react'
import { useNavigate } from 'react-router-dom'

import { Panel, PanelEmpty } from '@/app/overlays/panel'
import { SAVINGS_ROUTE } from '@/app/routes'
import { formatExactTokens, formatPct, formatTokens } from '@/app/savings/format'
import { cumulativeFromTimeSeries, cumulativeSavedSeries } from '@/app/savings/parse'
import { useSavingsData } from '@/app/savings/use-savings-data'
import { PageLoader } from '@/components/page-loader'
import { ByModelBars, ByProofDonut } from '@/components/savings/dimension-charts'
import { HeroStat } from '@/components/savings/hero-stat'
import { LiveActivity } from '@/components/savings/live-activity'
import { McpStatusChip } from '@/components/savings/mcp-status-chip'
import { SavingsChart } from '@/components/savings/savings-chart'
import { SessionEventsTable } from '@/components/savings/session-events-table'
import { SessionsList } from '@/components/savings/sessions-list'
import { StatusCards } from '@/components/savings/status-cards'
import { useThresholdCrossing } from '@/components/savings/use-threshold-crossing'
import { Button } from '@/components/ui/button'
import { useI18n } from '@/i18n'
import { RefreshCw, Wrench } from '@/lib/icons'
import { cn } from '@/lib/utils'
import { $desktopOnboarding, startManualPostSetup } from '@/store/onboarding'

interface TokenMonitorProps {
  onClose: () => void
}

// Vite serves public/ at the base URL (same pattern as brand-mark.tsx).
const assetPath = (path: string) => `${import.meta.env.BASE_URL}${path.replace(/^\/+/, '')}`

// Runtime cockpit: at a glance MCP + local LLM + neural DB health, evidenced
// token savings (measured vs estimated, hash-chained ledger), and each run as
// an auditable timeline. Backed by `window.simplicioSavings`; never
// fabricates a figure — every unknown field renders as "—" and every surface
// carries its own honest unavailable/error state.
export default function TokenMonitor({ onClose }: TokenMonitorProps) {
  const { t } = useI18n()
  const s = t.savings
  const { doctor, mcp, mcpControl, memory, refresh, refreshing, sessions, state } = useSavingsData()
  const navigate = useNavigate()

  // Diagnostics opens the (first-run-shaped) onboarding overlay via
  // startManualPostSetup(). That overlay renders as an opaque full-viewport
  // layer (z-1300, solid background) stacked ON TOP of this panel — it never
  // unmounts the savings route — but visually it looks like a replacement,
  // and once the sequence finishes it drops the user wherever `manual`
  // becoming false happens to leave the app (observed: Home), not back on
  // this cockpit. `onboarding.manual` flips true<-manualPostSetupPatch()
  // ->false via BOTH closeManualOnboarding() (cancel) and
  // completeDesktopOnboarding() (finish) — so watching that single flag
  // covers "closed early" and "completed" alike. The ref scopes the guard to
  // a flow *this button* launched, so an unrelated manual onboarding
  // (e.g. Settings -> Providers) never yanks the user into /savings.
  const onboardingManual = useStore($desktopOnboarding).manual
  const diagnosticsLaunchedRef = useRef(false)

  useEffect(() => {
    if (diagnosticsLaunchedRef.current && !onboardingManual) {
      diagnosticsLaunchedRef.current = false
      navigate(SAVINGS_ROUTE, { replace: true })
    }
  }, [navigate, onboardingManual])

  const openDiagnostics = () => {
    diagnosticsLaunchedRef.current = true
    startManualPostSetup()
  }

  const parsed = state.status === 'ok' ? state.parsed : null
  // Prefer the report's daily time_series dimension; fall back to building
  // the cumulative curve from raw events when the dimension is absent.
  const series = useMemo(() => {
    if (!parsed) {
      return []
    }

    const fromDimension = cumulativeFromTimeSeries(parsed.dimensions.timeSeries)

    return fromDimension.length >= 2 ? fromDimension : cumulativeSavedSeries(parsed.events)
  }, [parsed])
  const hasAnyData =
    parsed !== null && (parsed.events.length > 0 || parsed.totals.spent !== null || parsed.totals.baseline !== null)

  // Neon Burst: fires once when the overall savings rate crosses >=90%.
  const superSavings = useThresholdCrossing(parsed?.totals.pct ?? null, 90)

  const sessionsSection =
    sessions.status === 'ok' && sessions.data.sessions.length > 0 ? (
      <section className="savings-stagger-in" style={{ animationDelay: '300ms' }}>
        <div className="mb-1 text-[0.625rem] font-medium uppercase tracking-[0.08em] text-muted-foreground/60">
          {s.cockpit.sessionsTitle}
        </div>
        <p className="mb-3 text-xs text-muted-foreground/70">{s.cockpit.sessionsDesc}</p>
        <SessionsList data={sessions.data} />
      </section>
    ) : null

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
            <McpStatusChip mcp={mcp} />
          </div>
          <p className="mt-0.5 truncate text-xs text-muted-foreground/80">{s.subtitle}</p>
        </div>
        {/* Closes the loop "see status -> run the full diagnosis": jumps into
            the Setup Simplicio post-setup flow (doctor -> google -> subscription). */}
        <Button onClick={openDiagnostics} size="xs" title={s.cockpit.diagnostics} variant="outline">
          <Wrench className="size-3.5" />
          {s.cockpit.diagnostics}
        </Button>
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
        <div className="grid gap-6">
          <StatusCards doctor={doctor} mcp={mcp} mcpControl={mcpControl} memory={memory} refreshing={refreshing} />

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
            <>
              <PanelEmpty description={s.emptyDesc} icon="inbox" title={s.emptyTitle} />
              {sessionsSection}
            </>
          ) : (
            <>
              <section className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                <HeroStat
                  format={formatTokens}
                  glow
                  label={s.heroTotalSavedLabel}
                  staggerMs={0}
                  value={parsed.totals.saved}
                />
                <HeroStat
                  celebrate={superSavings.active}
                  celebrateBurstKey={superSavings.burstKey}
                  celebrateLabel={s.cockpit.superSavingsAria}
                  format={formatPct}
                  label={s.heroPctSavedLabel}
                  staggerMs={60}
                  value={parsed.totals.pct}
                />
                <HeroStat
                  format={formatTokens}
                  hint={
                    parsed.totals.baseline !== null ? s.heroSpentHint(formatTokens(parsed.totals.baseline)) : undefined
                  }
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

              {(parsed.dimensions.byModel.length > 0 || parsed.dimensions.byProof.length > 0) && (
                <div className="grid gap-6 lg:grid-cols-2">
                  <ByModelBars slices={parsed.dimensions.byModel} />
                  <ByProofDonut slices={parsed.dimensions.byProof} />
                </div>
              )}

              {sessionsSection}

              <section className="savings-stagger-in" style={{ animationDelay: '340ms' }}>
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
            </>
          )}

          {sessions.status === 'error' && (
            <p className="text-[0.66rem] text-destructive/80">{sessions.error}</p>
          )}

          {/* Independent of the savings-report state above: Live Activity has
              its own bridge (`dashboardStatus`/`dashboardSummary`) and its own
              unavailable/starting/loading/ok/error machinery, so it renders
              unconditionally here rather than nested in the branches above. */}
          <LiveActivity />
        </div>
      </div>
    </Panel>
  )
}
