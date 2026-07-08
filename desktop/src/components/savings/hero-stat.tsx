import type { ReactNode } from 'react'

import { NeonBurst } from '@/components/savings/neon-burst'
import { useCountUp } from '@/components/savings/use-count-up'
import { cn } from '@/lib/utils'

interface HeroStatProps {
  /** >=90% celebration: slow neon aura + sparkles while true. */
  celebrate?: boolean
  /** One-shot Neon Burst mount key from useThresholdCrossing (0 = none). */
  celebrateBurstKey?: number
  celebrateLabel?: string
  className?: string
  /** Formats the (possibly mid-animation, possibly null) numeric value for display. */
  format: (value: null | number) => string
  glow?: boolean
  hint?: ReactNode
  label: ReactNode
  /** Entrance-stagger delay in ms (cascade effect across the hero row). */
  staggerMs?: number
  value: null | number
}

// Fixed sparkle positions (percent) + phase delays for the >=90% state.
const SPARKLES = [
  { delay: '0ms', left: '12%', top: '18%' },
  { delay: '700ms', left: '86%', top: '30%' },
  { delay: '1400ms', left: '70%', top: '78%' }
] as const

// Animated hero metric card: count-up via requestAnimationFrame, soft
// green-neon glow on the number when `glow` is set. When `celebrate` is on
// (savings >= 90%) the number gains the slow "super" aura, fixed sparkles,
// and a one-shot Neon Burst keyed by `celebrateBurstKey`. Under reduced
// motion the CSS swaps all of that for a static glowing badge.
export function HeroStat({
  celebrate,
  celebrateBurstKey = 0,
  celebrateLabel,
  className,
  format,
  glow,
  hint,
  label,
  staggerMs = 0,
  value
}: HeroStatProps) {
  const animated = useCountUp(value)

  return (
    <div
      aria-label={celebrate && celebrateLabel ? celebrateLabel : undefined}
      className={cn(
        'savings-stagger-in relative min-w-0 rounded-lg border border-(--ui-stroke-tertiary) bg-(--ui-bg-tertiary) px-4 py-3',
        'transition-transform duration-150 ease-out hover:-translate-y-0.5',
        className
      )}
      style={{ animationDelay: `${staggerMs}ms` }}
    >
      <div className="text-[0.62rem] font-medium uppercase tracking-[0.1em] text-muted-foreground/70">{label}</div>
      <div className="relative mt-1 flex items-baseline gap-2">
        <span
          className={cn(
            'truncate text-2xl font-semibold tabular-nums tracking-tight text-foreground',
            glow && value !== null && 'savings-neon-text',
            celebrate && 'savings-super'
          )}
        >
          {format(animated)}
        </span>
        {celebrate && (
          <span className="savings-super-badge items-center rounded-full border border-emerald-500/50 px-1.5 py-0.5 text-[0.6rem] font-semibold text-emerald-500">
            90%+
          </span>
        )}
        {celebrate &&
          SPARKLES.map(sparkle => (
            <span
              aria-hidden="true"
              className="savings-sparkle pointer-events-none absolute size-1 rounded-full"
              key={sparkle.delay}
              style={{ animationDelay: sparkle.delay, left: sparkle.left, top: sparkle.top }}
            />
          ))}
        {celebrate && celebrateBurstKey > 0 && <NeonBurst key={celebrateBurstKey} />}
      </div>
      {hint && <div className="mt-1 truncate text-[0.68rem] text-muted-foreground/60">{hint}</div>}
    </div>
  )
}
