import { type ReactNode, useEffect, useState } from 'react'

import { type DoctorInfo, guardianTone, llmHealthy, type MemoryInfo } from '@/app/savings/cockpit'
import type { CockpitState, McpControl } from '@/app/savings/use-savings-data'
import { Tip } from '@/components/ui/tooltip'
import { useI18n } from '@/i18n'
import { Loader2 } from '@/lib/icons'
import { cn } from '@/lib/utils'

import type { McpDaemonStatus } from '@/app/savings/types'

// -- shared card chrome ------------------------------------------------------

type CardTone = 'bad' | 'good' | 'loading' | 'unknown' | 'warn'

const DOT_TONE: Record<CardTone, string> = {
  bad: 'bg-destructive',
  good: 'savings-pulse-good bg-emerald-500',
  loading: 'bg-muted-foreground/40',
  unknown: 'bg-muted-foreground/40',
  warn: 'bg-amber-500'
}

function StatusCard({
  children,
  label,
  refreshing,
  staggerMs,
  title,
  tone
}: {
  children: ReactNode
  label: string
  refreshing?: boolean
  staggerMs: number
  title: string
  tone: CardTone
}) {
  return (
    <div
      className={cn(
        'savings-stagger-in min-w-0 rounded-lg border border-(--ui-stroke-tertiary) bg-(--ui-bg-tertiary) px-3.5 py-3',
        'transition-transform duration-150 ease-out hover:-translate-y-0.5'
      )}
      style={{ animationDelay: `${staggerMs}ms` }}
    >
      <div className="flex items-center gap-1.5">
        {tone === 'loading' ? (
          <Loader2 aria-hidden="true" className="size-2.5 shrink-0 animate-spin text-muted-foreground/60" />
        ) : (
          <span aria-hidden="true" className={cn('size-1.5 shrink-0 rounded-full', DOT_TONE[tone])} />
        )}
        <span className="truncate text-[0.6rem] font-medium uppercase tracking-[0.1em] text-muted-foreground/70">
          {label}
        </span>
        {/* Stale-while-revalidate: resolved data stays visible; this discreet
            spinner is the only refresh signal on the card. */}
        {refreshing && tone !== 'loading' && (
          <Loader2 aria-hidden="true" className="ml-auto size-2.5 shrink-0 animate-spin text-muted-foreground/40" />
        )}
      </div>
      <div className="mt-1.5 truncate text-[0.82rem] font-semibold text-foreground" title={title}>
        {title}
      </div>
      <div className="mt-1 min-h-4 text-[0.66rem] text-muted-foreground/70">{children}</div>
    </div>
  )
}

/** In-flight skeleton — the method EXISTS and its IPC call is resolving.
 * Distinct from UnavailableCard by contract: never says "bridge missing". */
function LoadingCard({ label, staggerMs }: { label: string; staggerMs: number }) {
  const { t } = useI18n()
  const s = t.savings

  return (
    <StatusCard label={label} staggerMs={staggerMs} title={s.cockpit.checking} tone="loading">
      <span aria-hidden="true" className="block h-2 w-2/3 animate-pulse rounded bg-foreground/8" />
    </StatusCard>
  )
}

/** The method genuinely is not exposed by this build (sync typeof probe) or
 * a fetch resolved with a real error — never shown for an in-flight fetch. */
function UnavailableCard({ error, label, staggerMs }: { error?: string; label: string; staggerMs: number }) {
  const { t } = useI18n()
  const s = t.savings

  return (
    <StatusCard label={label} staggerMs={staggerMs} title={s.cockpit.unavailable} tone={error ? 'bad' : 'unknown'}>
      <span className="line-clamp-2 break-words">{error ?? s.cockpit.bridgeMissing}</span>
    </StatusCard>
  )
}

/** Shared loading/unavailable/error handling for a surface-backed card. */
function SurfaceCard<T>({
  children,
  label,
  staggerMs,
  state
}: {
  children: (data: T) => ReactNode
  label: string
  staggerMs: number
  state: CockpitState<T>
}) {
  if (state.status === 'loading') {
    return <LoadingCard label={label} staggerMs={staggerMs} />
  }

  if (state.status !== 'ok') {
    return <UnavailableCard error={state.status === 'error' ? state.error : undefined} label={label} staggerMs={staggerMs} />
  }

  return <>{children(state.data)}</>
}

const UNKNOWN = '—'

// -- MCP server ---------------------------------------------------------------

function uptimeLabel(startedAt: string | undefined): null | string {
  if (!startedAt) {
    return null
  }

  const ms = Date.parse(startedAt)

  if (!Number.isFinite(ms)) {
    return null
  }

  const minutes = Math.max(0, Math.floor((Date.now() - ms) / 60_000))

  if (minutes < 60) {
    return `${minutes}m`
  }

  const hours = Math.floor(minutes / 60)

  return hours < 48 ? `${hours}h ${minutes % 60}m` : `${Math.floor(hours / 24)}d`
}

/** Stop needs a light inline confirmation: first click flips the label to
 * "confirm stop?" for 3s; a second click within the window executes. */
function DaemonControls({ control, running }: { control: McpControl; running: boolean }) {
  const { t } = useI18n()
  const s = t.savings
  const [confirmingStop, setConfirmingStop] = useState(false)

  useEffect(() => {
    if (!confirmingStop) {
      return
    }

    const id = window.setTimeout(() => setConfirmingStop(false), 3000)

    return () => window.clearTimeout(id)
  }, [confirmingStop])

  if (!control.canControl) {
    return null
  }

  if (running) {
    return (
      <button
        className={cn(
          'inline-flex h-5 items-center rounded border px-1.5 text-[0.6rem] font-medium transition-colors disabled:opacity-50',
          confirmingStop
            ? 'border-destructive/50 bg-destructive/10 text-destructive'
            : 'border-transparent text-muted-foreground/70 hover:border-(--ui-stroke-tertiary) hover:text-foreground'
        )}
        disabled={control.pending}
        onClick={() => {
          if (confirmingStop) {
            setConfirmingStop(false)
            control.stop()
          } else {
            setConfirmingStop(true)
          }
        }}
        type="button"
      >
        {control.pending ? (
          <Loader2 aria-hidden="true" className="size-2.5 animate-spin" />
        ) : confirmingStop ? (
          s.cockpit.confirmStop
        ) : (
          s.cockpit.stopAction
        )}
      </button>
    )
  }

  return (
    <button
      className="inline-flex h-5 items-center rounded border border-emerald-500/50 bg-emerald-500/10 px-1.5 text-[0.6rem] font-semibold text-emerald-600 transition-colors hover:bg-emerald-500/20 disabled:opacity-50 dark:text-emerald-400"
      disabled={control.pending}
      onClick={() => control.start()}
      type="button"
    >
      {control.pending ? <Loader2 aria-hidden="true" className="size-2.5 animate-spin" /> : s.cockpit.startAction}
    </button>
  )
}

function McpCard({
  control,
  mcp,
  refreshing,
  staggerMs
}: {
  control: McpControl
  mcp: CockpitState<McpDaemonStatus>
  refreshing: boolean
  staggerMs: number
}) {
  const { t } = useI18n()
  const s = t.savings

  return (
    <SurfaceCard label={s.cockpit.mcpLabel} staggerMs={staggerMs} state={mcp}>
      {status => {
        const uptime = uptimeLabel(status.startedAt)

        return (
          <StatusCard
            label={s.cockpit.mcpLabel}
            refreshing={refreshing}
            staggerMs={staggerMs}
            title={status.running ? s.cockpit.running : s.cockpit.stopped}
            tone={status.running ? 'good' : 'bad'}
          >
            <div className="flex items-start justify-between gap-2">
              {status.running ? (
                <span>
                  {status.pid ? `pid ${status.pid}` : UNKNOWN}
                  {uptime ? ` · ${s.cockpit.uptime(uptime)}` : ''}
                  {status.restarts > 0 ? ` · ${s.mcpRestarts(status.restarts)}` : ''}
                </span>
              ) : (
                <span className="line-clamp-2 break-words text-destructive/90">
                  {status.lastError ?? s.mcpStoppedNoDetail}
                </span>
              )}
              <DaemonControls control={control} running={status.running} />
            </div>
            {control.error && (
              <p className="mt-1 line-clamp-2 break-words text-[0.6rem] text-destructive/90">{control.error}</p>
            )}
          </StatusCard>
        )
      }}
    </SurfaceCard>
  )
}

// -- Local LLM ----------------------------------------------------------------

function LlmCard({ doctor, refreshing, staggerMs }: { doctor: CockpitState<DoctorInfo>; refreshing: boolean; staggerMs: number }) {
  const { t } = useI18n()
  const s = t.savings

  return (
    <SurfaceCard label={s.cockpit.llmLabel} staggerMs={staggerMs} state={doctor}>
      {info => {
        const healthy = llmHealthy(info)

        return (
          <StatusCard
            label={s.cockpit.llmLabel}
            refreshing={refreshing}
            staggerMs={staggerMs}
            title={info.model ?? s.cockpit.noModel}
            tone={healthy ? 'good' : info.model ? 'warn' : 'bad'}
          >
            <span>
              {info.local === true ? s.cockpit.local : info.local === false ? s.cockpit.remote : UNKNOWN}
              {info.offlineFirst === true ? ` · ${s.cockpit.offlineFirst}` : ''}
            </span>
          </StatusCard>
        )
      }}
    </SurfaceCard>
  )
}

// -- Neural DB + guardians ------------------------------------------------------

const GUARDIAN_DOT: Record<ReturnType<typeof guardianTone>, string> = {
  good: 'bg-emerald-500',
  info: 'bg-sky-500',
  muted: 'bg-muted-foreground/40',
  warn: 'bg-amber-500'
}

function NeuralCard({ memory, refreshing, staggerMs }: { memory: CockpitState<MemoryInfo>; refreshing: boolean; staggerMs: number }) {
  const { t } = useI18n()
  const s = t.savings

  return (
    <SurfaceCard label={s.cockpit.neuralLabel} staggerMs={staggerMs} state={memory}>
      {info => {
        const ready = info.status === 'ready'

        return (
          <StatusCard
            label={s.cockpit.neuralLabel}
            refreshing={refreshing}
            staggerMs={staggerMs}
            title={
              info.memoryItems !== null ? s.cockpit.memories(info.memoryItems.toLocaleString()) : (info.status ?? UNKNOWN)
            }
            tone={ready ? 'good' : info.status ? 'warn' : 'unknown'}
          >
            <div className="flex flex-wrap items-center gap-1">
              {info.backend && <span className="font-mono text-[0.62rem]">{info.backend}</span>}
              {info.guardians.map(guardian => {
                const tone = guardianTone(guardian.status)

                return (
                  <Tip
                    key={guardian.name}
                    label={`${guardian.name}${guardian.role ? ` · ${guardian.role}` : ''}${guardian.status ? ` (${guardian.status})` : ''}`}
                  >
                    <span className="inline-flex items-center gap-1 rounded-full border border-(--ui-stroke-tertiary) px-1.5 py-px text-[0.6rem] font-medium text-foreground/80 transition-colors hover:border-(--ui-stroke-primary)">
                      <span aria-hidden="true" className={cn('size-1 rounded-full', GUARDIAN_DOT[tone])} />
                      {guardian.name}
                    </span>
                  </Tip>
                )
              })}
            </div>
          </StatusCard>
        )
      }}
    </SurfaceCard>
  )
}

// -- Runtime -------------------------------------------------------------------

function RuntimeCard({ doctor, refreshing, staggerMs }: { doctor: CockpitState<DoctorInfo>; refreshing: boolean; staggerMs: number }) {
  const { t } = useI18n()
  const s = t.savings

  return (
    <SurfaceCard label={s.cockpit.runtimeLabel} staggerMs={staggerMs} state={doctor}>
      {info => {
        const tone: CardTone =
          info.overallStatus === 'ok'
            ? 'good'
            : info.overallStatus === 'warning'
              ? 'warn'
              : info.overallStatus === 'error'
                ? 'bad'
                : 'unknown'

        return (
          <StatusCard
            label={s.cockpit.runtimeLabel}
            refreshing={refreshing}
            staggerMs={staggerMs}
            title={info.version ? `v${info.version.replace(/^v/, '')}` : UNKNOWN}
            tone={tone}
          >
            <span className="line-clamp-2 break-all font-mono text-[0.6rem]" title={info.binary ?? undefined}>
              {info.overallStatus ?? UNKNOWN}
              {info.binary ? ` · ${info.binary}` : ''}
            </span>
          </StatusCard>
        )
      }}
    </SurfaceCard>
  )
}

// -- row -----------------------------------------------------------------------

export function StatusCards({
  doctor,
  mcp,
  mcpControl,
  memory,
  refreshing
}: {
  doctor: CockpitState<DoctorInfo>
  mcp: CockpitState<McpDaemonStatus>
  mcpControl: McpControl
  memory: CockpitState<MemoryInfo>
  refreshing: boolean
}) {
  return (
    <section className="grid grid-cols-2 gap-3 xl:grid-cols-4">
      <McpCard control={mcpControl} mcp={mcp} refreshing={refreshing} staggerMs={0} />
      <LlmCard doctor={doctor} refreshing={refreshing} staggerMs={50} />
      <NeuralCard memory={memory} refreshing={refreshing} staggerMs={100} />
      <RuntimeCard doctor={doctor} refreshing={refreshing} staggerMs={150} />
    </section>
  )
}
