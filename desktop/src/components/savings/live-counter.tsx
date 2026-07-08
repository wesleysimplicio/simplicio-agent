import { useEffect, useRef, useState } from 'react'

import { useCountUp } from '@/components/savings/use-count-up'
import { cn } from '@/lib/utils'

// A hero counter that re-animates on every value change (not just once):
// `useCountUp` already tweens from its previously-committed value to the new
// target on every render where `value` changes, so the count-up half of this
// is free. What this component adds is the flash highlight — a brief
// background tint (CSS `savings-live-flash`, ~550ms one-shot) that fires
// each time the *committed* value actually differs from the last one,
// distinguishing "value just changed" from "component just mounted" (no
// flash on first render — nothing changed relative to nothing).

const FLASH_MS = 600

function prefersReducedMotion(): boolean {
  return typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches === true
}

interface LiveCounterProps {
  format: (value: null | number) => string
  label: string
}

export function LiveCounter({ format, label, value }: LiveCounterProps & { value: null | number }) {
  const animated = useCountUp(value)
  const [flashing, setFlashing] = useState(false)
  const prevValueRef = useRef<null | number>(value)
  const mountedRef = useRef(false)

  useEffect(() => {
    if (!mountedRef.current) {
      // First render: nothing to flash against.
      mountedRef.current = true
      prevValueRef.current = value

      return
    }

    if (value !== prevValueRef.current) {
      prevValueRef.current = value

      if (!prefersReducedMotion()) {
        setFlashing(true)
        const id = window.setTimeout(() => setFlashing(false), FLASH_MS)

        return () => window.clearTimeout(id)
      }
    }
  }, [value])

  return (
    <div
      className={cn(
        'min-w-0 rounded-lg border border-(--ui-stroke-tertiary) bg-(--ui-bg-tertiary) px-3 py-2.5 transition-colors',
        flashing && 'savings-live-flash'
      )}
    >
      <div className="text-[0.58rem] font-medium uppercase tracking-[0.08em] text-muted-foreground/65">{label}</div>
      <div className="mt-0.5 truncate text-lg font-semibold tabular-nums tracking-tight text-foreground">
        {format(animated)}
      </div>
    </div>
  )
}
