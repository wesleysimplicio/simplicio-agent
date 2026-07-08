import { useEffect, useState } from 'react'

import { formatRelativeTime } from '@/app/savings/live-format'
import { useI18n } from '@/i18n'
import { cn } from '@/lib/utils'

// Header "AO VIVO" indicator: a pulsing dot (<=1Hz, reuses the existing
// `savings-pulse-good` keyframe) plus a relative-time label recomputed every
// second. When `pulseKey` advances (a genuinely new generation of data just
// landed — see `dashboard-diff.ts`) a one-shot expanding ring fires once.
// Under `prefers-reduced-motion` the pulse and ring never animate and the
// label swaps to a static "Active" badge — the honest fallback, not a lesser
// version of the same claim.

function prefersReducedMotion(): boolean {
  return typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches === true
}

interface LiveBadgeProps {
  /** Increments each time Live Activity detects a new generation of data;
   * 0 means "never yet" (no ring on first load). */
  pulseKey: number
  updatedAtMs: null | number
}

export function LiveBadge({ pulseKey, updatedAtMs }: LiveBadgeProps) {
  const { t } = useI18n()
  const s = t.savings.live
  const [now, setNow] = useState(() => Date.now())
  const reduced = prefersReducedMotion()

  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 1000)

    return () => window.clearInterval(id)
  }, [])

  const relative = formatRelativeTime(updatedAtMs, now)
  const updatedLabel = relative === null ? null : relative === 'now' ? s.updatedNow : s.updatedAgo(relative)

  return (
    <span className="inline-flex items-center gap-1.5 text-[0.65rem] font-medium text-emerald-600 dark:text-emerald-400">
      <span className="relative inline-flex size-2 shrink-0 items-center justify-center">
        <span aria-hidden="true" className={cn('absolute inset-0 rounded-full bg-emerald-500', !reduced && 'savings-pulse-good')} />
        {!reduced && pulseKey > 0 && (
          <svg aria-hidden="true" className="absolute -inset-2.5 overflow-visible" height="18" viewBox="-9 -9 18 18" width="18">
            <circle
              className="savings-live-ring"
              cx="0"
              cy="0"
              fill="none"
              key={pulseKey}
              r="3"
              stroke="var(--savings-accent, #39ff14)"
              strokeWidth="1.5"
            />
          </svg>
        )}
      </span>
      {reduced ? s.badgeStatic : s.badgeLive}
      {updatedLabel && <span className="font-normal text-muted-foreground/70">· {updatedLabel}</span>}
    </span>
  )
}
