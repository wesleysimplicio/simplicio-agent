import type { McpDaemonStatus } from '@/app/savings/types'
import { Tip } from '@/components/ui/tooltip'
import { useI18n } from '@/i18n'
import { cn } from '@/lib/utils'

interface McpStatusChipProps {
  status: McpDaemonStatus | null
}

// Header chip for the MCP daemon (`simplicio serve --mcp`) — green pulsing
// dot while running, red static dot with the real lastError when stopped,
// neutral while the bridge hasn't reported yet.
export function McpStatusChip({ status }: McpStatusChipProps) {
  const { t } = useI18n()
  const s = t.savings

  if (!status) {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full border border-(--ui-stroke-tertiary) px-2 py-0.5 text-[0.65rem] text-muted-foreground">
        <span aria-hidden="true" className="size-1.5 rounded-full bg-muted-foreground/40" />
        {s.mcpUnknown}
      </span>
    )
  }

  const detail = status.running
    ? status.pid
      ? s.mcpRunningPid(status.pid)
      : s.mcpRunning
    : status.lastError || s.mcpStoppedNoDetail

  return (
    <Tip label={detail}>
      <span
        className={cn(
          'inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[0.65rem] font-medium',
          status.running
            ? 'border-emerald-500/40 text-emerald-600 dark:text-emerald-400'
            : 'border-destructive/40 text-destructive'
        )}
      >
        <span
          aria-hidden="true"
          className={cn(
            'size-1.5 rounded-full',
            status.running ? 'savings-pulse-good bg-emerald-500' : 'bg-destructive'
          )}
        />
        {status.running ? s.mcpRunning : s.mcpStopped}
        {status.restarts > 0 && <span className="text-muted-foreground/70">· {s.mcpRestarts(status.restarts)}</span>}
      </span>
    </Tip>
  )
}
