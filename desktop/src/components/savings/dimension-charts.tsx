import type { DimensionSlice } from '@/app/savings/parse'
import { formatPct, formatTokens } from '@/app/savings/format'
import { useI18n } from '@/i18n'
import { cn } from '@/lib/utils'

// Dimension breakdowns from `report.dimensions` — pure SVG/CSS, no chart lib.
// Both components render nothing for an empty dimension: an absent breakdown
// is absent, not a placeholder.

// -- by_model: horizontal bars -------------------------------------------------

export function ByModelBars({ slices }: { slices: readonly DimensionSlice[] }) {
  const { t } = useI18n()
  const s = t.savings
  const usable = slices.filter(slice => slice.savedTotal !== null)

  if (usable.length === 0) {
    return null
  }

  const max = Math.max(...usable.map(slice => slice.savedTotal ?? 0), 1)

  return (
    <section className="savings-stagger-in min-w-0" style={{ animationDelay: '220ms' }}>
      <div className="mb-2 text-[0.625rem] font-medium uppercase tracking-[0.08em] text-muted-foreground/60">
        {s.cockpit.byModelTitle}
      </div>
      <div className="grid gap-1.5">
        {usable
          .slice()
          .sort((a, b) => (b.savedTotal ?? 0) - (a.savedTotal ?? 0))
          .slice(0, 8)
          .map(slice => (
            <div className="group grid grid-cols-[minmax(0,10rem)_1fr_auto] items-center gap-2" key={slice.key}>
              <span className="truncate font-mono text-[0.66rem] text-foreground/80" title={slice.key}>
                {slice.key}
              </span>
              <div className="h-2 overflow-hidden rounded-full bg-foreground/8">
                <div
                  className="h-full rounded-full bg-[color:var(--savings-accent,#39ff14)]/70 transition-[width] duration-500 ease-out group-hover:bg-[color:var(--savings-accent,#39ff14)]"
                  style={{ width: `${Math.max(2, Math.round(((slice.savedTotal ?? 0) / max) * 100))}%` }}
                />
              </div>
              <span className="shrink-0 text-right text-[0.62rem] tabular-nums text-muted-foreground/70">
                {formatTokens(slice.savedTotal)}
                {slice.savedPercent !== null ? ` (${formatPct(slice.savedPercent)})` : ''}
              </span>
            </div>
          ))}
      </div>
    </section>
  )
}

// -- by_proof: donut (measured green solid vs estimated amber) -------------------

const PROOF_COLORS: Record<string, string> = {
  estimated: '#f59e0b',
  measured: '#22c55e'
}

const DONUT_R = 34
const DONUT_C = 2 * Math.PI * DONUT_R

export function ByProofDonut({ slices }: { slices: readonly DimensionSlice[] }) {
  const { t } = useI18n()
  const s = t.savings
  const usable = slices.filter(slice => slice.savedTotal !== null && (slice.savedTotal ?? 0) > 0)
  const total = usable.reduce((acc, slice) => acc + (slice.savedTotal ?? 0), 0)

  if (usable.length === 0 || total <= 0) {
    return null
  }

  let offset = 0
  const arcs = usable.map(slice => {
    const fraction = (slice.savedTotal ?? 0) / total
    const arc = { fraction, key: slice.key, offset, value: slice.savedTotal ?? 0 }
    offset += fraction

    return arc
  })

  return (
    <section className="savings-stagger-in min-w-0" style={{ animationDelay: '260ms' }}>
      <div className="mb-2 text-[0.625rem] font-medium uppercase tracking-[0.08em] text-muted-foreground/60">
        {s.cockpit.byProofTitle}
      </div>
      <div className="flex items-center gap-4">
        <svg aria-hidden="true" className="shrink-0" height="88" viewBox="0 0 88 88" width="88">
          <circle cx="44" cy="44" fill="none" r={DONUT_R} stroke="currentColor" strokeOpacity="0.08" strokeWidth="9" />
          {arcs.map(arc => (
            <circle
              cx="44"
              cy="44"
              fill="none"
              key={arc.key}
              r={DONUT_R}
              stroke={PROOF_COLORS[arc.key] ?? 'var(--ui-text-quaternary)'}
              strokeDasharray={`${Math.max(0.5, arc.fraction * DONUT_C)} ${DONUT_C}`}
              strokeDashoffset={-arc.offset * DONUT_C}
              strokeLinecap="butt"
              strokeWidth="9"
              transform="rotate(-90 44 44)"
            />
          ))}
        </svg>
        <ul className="grid gap-1">
          {arcs.map(arc => (
            <li className="flex items-center gap-1.5 text-[0.68rem]" key={arc.key}>
              <span
                aria-hidden="true"
                className={cn('size-2 rounded-[2px]', arc.key === 'estimated' && 'border border-amber-500 bg-transparent')}
                style={arc.key === 'estimated' ? undefined : { background: PROOF_COLORS[arc.key] ?? 'var(--ui-text-quaternary)' }}
              />
              <span className="capitalize text-foreground/80">
                {arc.key === 'measured' ? s.measuredLabel : arc.key === 'estimated' ? s.estimatedLabel : arc.key}
              </span>
              <span className="tabular-nums text-muted-foreground/70">
                {formatTokens(arc.value)} ({Math.round(arc.fraction * 100)}%)
              </span>
            </li>
          ))}
        </ul>
      </div>
    </section>
  )
}
