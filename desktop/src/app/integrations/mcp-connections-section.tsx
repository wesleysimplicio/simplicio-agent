import { useEffect, useState } from 'react'

import { Codicon } from '@/components/ui/codicon'
import { Tip } from '@/components/ui/tooltip'
import type { Translations } from '@/i18n'
import { useI18n } from '@/i18n'
import { cn } from '@/lib/utils'

import { editorAccentClass, editorMonogram } from './editor-presentation'
import { formatConnectionElapsed, type McpLiveConnection } from './mcp-connections-presentation'
import type { McpConnectionsState } from './use-mcp-connections'

// "Active MCP Connections" — the real-time complement to the Editors & agents
// grid above it: that grid shows static installed/registered-in-config state
// (from `simplicio mcp register`'s output), this section shows which MCP
// clients are ACTUALLY connected right now (`simplicio mcp status --json`,
// pid + the clientInfo the handshake received + tools called), polled every
// ~3.5s. An older runtime binary that predates the subcommand renders the
// honest "unavailable" state with the real backend error instead — never a
// fabricated connection, per the project's no-fake-data rule.

function prefersReducedMotion(): boolean {
  return typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches === true
}

function useNow(intervalMs: number): number {
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), intervalMs)

    return () => window.clearInterval(id)
  }, [intervalMs])

  return now
}

interface ConnectionRowProps {
  connection: McpLiveConnection
  copy: Translations['integrations']
  index: number
  now: number
}

function ConnectionRow({ connection, copy, index, now }: ConnectionRowProps) {
  const s = copy.mcpLive
  const reduced = prefersReducedMotion()
  const displayName = connection.clientName ?? s.unknownClient
  const editorIdGuess = connection.clientName ?? displayName
  const sinceLabel = connection.alive
    ? formatConnectionElapsed(connection.connectedAtMs, now)
    : formatConnectionElapsed(connection.lastToolCallAtMs ?? connection.connectedAtMs, now)

  return (
    <div
      className={cn(
        'savings-stagger-in flex items-start gap-3 rounded-[10px] border px-3.5 py-3',
        connection.alive
          ? 'border-emerald-500/30 bg-emerald-500/[0.03]'
          : 'border-(--ui-stroke-secondary) bg-(--ui-bg-secondary) opacity-60'
      )}
      style={{ animationDelay: `${Math.min(index, 8) * 40}ms` }}
    >
      <div
        aria-hidden="true"
        className={cn(
          'grid size-9 shrink-0 place-items-center rounded-[8px] text-[0.7rem] font-semibold tracking-tight',
          editorAccentClass(editorIdGuess)
        )}
      >
        {editorMonogram(editorIdGuess, displayName)}
      </div>

      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
          <span
            className={cn(
              'truncate text-sm font-medium',
              connection.alive ? 'text-foreground' : 'text-muted-foreground line-through decoration-1'
            )}
          >
            {displayName}
          </span>
          {connection.alive ? (
            <span className="inline-flex items-center gap-1 rounded-full border border-emerald-500/40 px-1.5 py-0.5 text-[0.6rem] font-medium text-emerald-600 dark:text-emerald-400">
              <span aria-hidden="true" className={cn('size-1.5 rounded-full bg-emerald-500', !reduced && 'savings-pulse-good')} />
              {s.connectedBadge}
            </span>
          ) : (
            <span className="text-[0.6rem] text-muted-foreground/70">{s.disconnectedBadge}</span>
          )}
        </div>

        <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[0.68rem] text-muted-foreground">
          {connection.pid !== null && <span>{s.pidLabel(connection.pid)}</span>}
          {connection.clientVersion && <span>{s.versionLabel(connection.clientVersion)}</span>}
          {sinceLabel && <span>{s.connectedSince(sinceLabel)}</span>}
          {connection.repo && (
            <span className="truncate font-mono text-[0.62rem] text-(--ui-text-quaternary)" title={connection.repo}>
              {connection.repo}
            </span>
          )}
        </div>

        {connection.toolsUsed.length > 0 ? (
          <div className="mt-1.5 flex flex-wrap gap-1">
            {connection.toolsUsed.map(tool => (
              <span
                className="rounded border border-(--ui-stroke-tertiary) bg-(--ui-bg-quinary) px-1 py-px font-mono text-[0.58rem] text-foreground/75"
                key={tool}
              >
                {tool}
              </span>
            ))}
          </div>
        ) : (
          connection.alive && <div className="mt-1.5 text-[0.62rem] text-muted-foreground/60">{s.noToolsYet}</div>
        )}
      </div>
    </div>
  )
}

function SectionSkeleton() {
  return (
    <div aria-hidden="true" className="grid gap-2">
      {[0, 1].map(i => (
        <div
          className="h-[4.5rem] animate-pulse rounded-[10px] border border-(--ui-stroke-secondary) bg-(--ui-bg-secondary) motion-reduce:animate-none"
          key={i}
          style={{ animationDelay: `${i * 80}ms` }}
        />
      ))}
    </div>
  )
}

export interface McpConnectionsSectionProps {
  className?: string
  // Lifted to the parent (`index.tsx`) so a single poll instance also drives
  // the "live now" badge cross-referenced onto the static Editors & agents
  // grid above this section — two independent `useMcpConnections()` polls
  // would double the IPC traffic for no benefit.
  state: McpConnectionsState
}

export function McpConnectionsSection({ className, state }: McpConnectionsSectionProps) {
  const { t } = useI18n()
  const c = t.integrations
  const s = c.mcpLive
  const now = useNow(1000)

  const updatedLabel =
    state.status === 'ok'
      ? (() => {
          const elapsed = formatConnectionElapsed(state.updatedAtMs, now)

          return elapsed === null || elapsed === '0s' ? s.updatedNow : s.updatedAgo(elapsed)
        })()
      : null

  return (
    <section className={className}>
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-xs font-semibold uppercase tracking-[0.08em] text-muted-foreground">{s.heading}</h2>
        {state.status === 'ok' && (
          <span className="text-[0.62rem] text-muted-foreground/60">{updatedLabel}</span>
        )}
      </div>
      <p className="mb-2 text-xs text-muted-foreground">{s.subtitle}</p>

      {state.status === 'loading' && <SectionSkeleton />}

      {state.status === 'unavailable' && (
        <Tip label={state.error}>
          <div className="flex items-center gap-2 rounded-md border border-(--ui-stroke-secondary) bg-(--ui-bg-secondary) px-3 py-2.5 text-xs text-muted-foreground">
            <Codicon aria-hidden className="shrink-0 text-muted-foreground/60" name="debug-disconnect" size="0.875rem" />
            <div className="min-w-0">
              <div className="font-medium text-foreground/85">{s.unavailableTitle}</div>
              <div className="mt-0.5 truncate text-(--ui-text-quaternary)">{s.unavailableDesc(state.error)}</div>
            </div>
          </div>
        </Tip>
      )}

      {state.status === 'ok' && state.connections.length === 0 && (
        <div className="flex items-center gap-2 rounded-md border border-(--ui-stroke-secondary) bg-(--ui-bg-secondary) px-3 py-2.5 text-xs text-muted-foreground">
          <Codicon aria-hidden className="shrink-0 text-muted-foreground/50" name="inbox" size="0.875rem" />
          <div>
            <div className="font-medium text-foreground/85">{s.emptyTitle}</div>
            <div className="mt-0.5 text-(--ui-text-quaternary)">{s.emptyDesc}</div>
          </div>
        </div>
      )}

      {state.status === 'ok' && state.connections.length > 0 && (
        <div className="grid gap-2">
          {state.connections.map((connection, index) => (
            <ConnectionRow
              connection={connection}
              copy={c}
              index={index}
              key={`${connection.clientName ?? 'unknown'}-${connection.pid ?? index}-${connection.connectedAtMs ?? index}`}
              now={now}
            />
          ))}
        </div>
      )}
    </section>
  )
}
