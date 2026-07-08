import type { McpDaemonStatus } from '@/app/savings/types'
import type { CockpitState } from '@/app/savings/use-savings-data'
import { Tip } from '@/components/ui/tooltip'
import { useI18n } from '@/i18n'
import { Loader2 } from '@/lib/icons'
import { cn } from '@/lib/utils'

interface McpStatusChipProps {
  mcp: CockpitState<McpDaemonStatus>
}

// Header chip for the MCP daemon (`simplicio serve --mcp`) — green pulsing
// dot while running, red static dot with the real lastError when stopped.
// While the status IPC is in flight the chip says "checking" (spinner) —
// never "status unknown", which is reserved for a bridge that genuinely
// doesn't expose the method or a fetch that resolved with an error.
export function McpStatusChip({ mcp }: McpStatusChipProps) {
  const { t } = useI18n()
  const s = t.savings

  if (mcp.status === 'loading') {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full border border-(--ui-stroke-tertiary) px-2 py-0.5 text-[0.65rem] text-muted-foreground">
        <Loader2 aria-hidden="true" className="size-2.5 animate-spin" />
        {s.cockpit.checking}
      </span>
    )
  }

  if (mcp.status !== 'ok') {
    return (
      <Tip label={mcp.status === 'error' ? mcp.error : undefined}>
        <span className="inline-flex items-center gap-1.5 rounded-full border border-(--ui-stroke-tertiary) px-2 py-0.5 text-[0.65rem] text-muted-foreground">
          <span aria-hidden="true" className="size-1.5 rounded-full bg-muted-foreground/40" />
          {s.mcpUnknown}
        </span>
      </Tip>
    )
  }

  const status = mcp.data
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
