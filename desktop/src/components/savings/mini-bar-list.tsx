import type { DashboardDimensionSlice } from '@/app/savings/dashboard-parse'
import { formatTokens } from '@/app/savings/format'

// Compact horizontal-bar breakdown for a dashboard dimension (by_provider /
// by_repo) — top 5 by saved tokens. Deliberately smaller/quieter than
// `ByModelBars` in dimension-charts.tsx (this is a secondary Live Activity
// panel, not the report's headline chart), but shares its "absent dimension
// renders nothing" honesty rule: no placeholder bars for data that isn't there.

interface MiniBarListProps {
  slices: readonly DashboardDimensionSlice[]
  title: string
}

export function MiniBarList({ slices, title }: MiniBarListProps) {
  const usable = slices.filter(slice => slice.saved !== null && (slice.saved ?? 0) > 0)

  if (usable.length === 0) {
    return null
  }

  const top = usable
    .slice()
    .sort((a, b) => (b.saved ?? 0) - (a.saved ?? 0))
    .slice(0, 5)
  const max = Math.max(...top.map(slice => slice.saved ?? 0), 1)

  return (
    <div className="min-w-0">
      <div className="mb-1.5 text-[0.6rem] font-medium uppercase tracking-[0.08em] text-muted-foreground/60">
        {title}
      </div>
      <div className="grid gap-1">
        {top.map(slice => (
          <div className="grid grid-cols-[minmax(0,6.5rem)_1fr_auto] items-center gap-1.5" key={slice.key}>
            <span className="truncate font-mono text-[0.62rem] text-foreground/80" title={slice.key}>
              {slice.key}
            </span>
            <div className="h-1.5 overflow-hidden rounded-full bg-foreground/8">
              <div
                className="h-full rounded-full bg-[color:var(--savings-accent,#39ff14)]/60 transition-[width] duration-500 ease-out"
                style={{ width: `${Math.max(4, Math.round(((slice.saved ?? 0) / max) * 100))}%` }}
              />
            </div>
            <span className="shrink-0 text-right text-[0.58rem] tabular-nums text-muted-foreground/70">
              {formatTokens(slice.saved)}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}
