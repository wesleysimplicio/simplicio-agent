import type { ReactNode } from 'react'

import { useCountUp } from '@/components/savings/use-count-up'
import { cn } from '@/lib/utils'

interface HeroStatProps {
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

// Animated hero metric card: count-up via requestAnimationFrame, soft
// green-neon glow on the number when `glow` is set (used for the headline
// "total saved" card only, so the eye lands there first).
export function HeroStat({ className, format, glow, hint, label, staggerMs = 0, value }: HeroStatProps) {
  const animated = useCountUp(value)

  return (
    <div
      className={cn(
        'savings-stagger-in min-w-0 rounded-lg border border-(--ui-stroke-tertiary) bg-(--ui-bg-tertiary) px-4 py-3',
        'transition-transform duration-150 ease-out hover:-translate-y-0.5',
        className
      )}
      style={{ animationDelay: `${staggerMs}ms` }}
    >
      <div className="text-[0.62rem] font-medium uppercase tracking-[0.1em] text-muted-foreground/70">{label}</div>
      <div
        className={cn(
          'mt-1 truncate text-2xl font-semibold tabular-nums tracking-tight text-foreground',
          glow && value !== null && 'savings-neon-text'
        )}
      >
        {format(animated)}
      </div>
      {hint && <div className="mt-1 truncate text-[0.68rem] text-muted-foreground/60">{hint}</div>}
    </div>
  )
}
