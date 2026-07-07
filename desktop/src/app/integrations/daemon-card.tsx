import { StatusDot } from '@/components/status-dot'
import type { Translations } from '@/i18n'
import { cn } from '@/lib/utils'

import { daemonTone, formatDaemonUptime } from './editor-presentation'
import type { McpDaemonStatus } from './types'

interface DaemonCardProps {
  status: McpDaemonStatus | null
  copy: Translations['integrations']
}

// The local MCP server is meant to be always-on, so this card is the honesty
// anchor for the whole screen: a green pulse only when the backend actually
// reports `running: true`, red the moment it isn't, and a plain muted dot
// (no animation) when the bridge can't be reached at all.
export function DaemonCard({ status, copy }: DaemonCardProps) {
  const tone = daemonTone(status)
  const uptime = status?.startedAt ? formatDaemonUptime(status.startedAt) : null

  const detail = !status
    ? copy.backendUnavailable
    : status.running
      ? [
          copy.daemonRunning,
          status.pid != null ? copy.daemonPid(status.pid) : null,
          uptime ? copy.daemonUptime(uptime) : null,
          status.restarts > 0 ? copy.daemonRestarts(status.restarts) : null
        ]
          .filter((part): part is string => Boolean(part))
          .join(' · ')
      : [copy.daemonStopped, status.lastError ? copy.daemonLastError(status.lastError) : null]
          .filter((part): part is string => Boolean(part))
          .join(' · ')

  return (
    <div
      className={cn(
        'flex items-center gap-3 rounded-[10px] border border-(--ui-stroke-secondary) bg-(--ui-bg-secondary)',
        'px-4 py-3.5 transition-shadow duration-300 hover:shadow-[0_0_24px_-10px_var(--primary)]'
      )}
    >
      <span aria-hidden="true" className="relative grid size-8 shrink-0 place-items-center">
        {tone === 'good' && (
          <span className="absolute inline-flex size-3 animate-ping rounded-full bg-primary/60 motion-reduce:hidden" />
        )}
        <StatusDot className="relative size-3" tone={tone} />
      </span>

      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
          <span className="text-sm font-medium text-foreground">{copy.daemonTitle}</span>
          <span className="text-xs text-muted-foreground">{copy.daemonAlwaysOn}</span>
        </div>
        <div className="mt-0.5 truncate text-xs text-muted-foreground">{detail}</div>
      </div>
    </div>
  )
}
