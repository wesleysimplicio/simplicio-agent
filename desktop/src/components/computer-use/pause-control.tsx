import { useCallback, useEffect, useRef, useState } from 'react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { getComputerUsePaused, setComputerUsePaused } from '@/hermes'
import { useI18n } from '@/i18n'
import { Loader2, Monitor, Pause, Play } from '@/lib/icons'
import { cn } from '@/lib/utils'
import { notify, notifyError } from '@/store/notifications'

/**
 * Global killswitch for Computer Use. The backend defaults to auto-approving
 * computer-use tool calls (YOLO posture — see assistant-ui/tool/approval.tsx's
 * APPROVAL_TOOLS), so this pause flag is the REAL control surface, not
 * per-action confirmation: while paused, the agent cannot drive the mouse or
 * keyboard at all. Backed by `GET`/`PUT /api/tools/computer-use/pause`
 * (hermes.ts's getComputerUsePaused/setComputerUsePaused) -- independent of
 * whether cua-driver itself is installed/ready, so this renders regardless of
 * ComputerUsePanel's own install/permission gating.
 */
export function ComputerUsePauseControl() {
  const { t } = useI18n()
  const copy = t.computerUse
  const [paused, setPaused] = useState<boolean | null>(null)
  const [loading, setLoading] = useState(true)
  const [pending, setPending] = useState(false)
  const activeRef = useRef(true)

  useEffect(() => {
    activeRef.current = true

    void (async () => {
      try {
        const state = await getComputerUsePaused()
        if (activeRef.current) {
          setPaused(state.paused)
        }
      } catch (err) {
        if (activeRef.current) {
          notifyError(err, copy.statusLoadFailed)
        }
      } finally {
        if (activeRef.current) {
          setLoading(false)
        }
      }
    })()

    return () => {
      activeRef.current = false
    }
    // Only re-fetch across a real remount — copy.statusLoadFailed changing
    // with locale must not refire the request.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const toggle = useCallback(async () => {
    if (paused === null || pending) {
      return
    }

    const next = !paused

    setPending(true)

    try {
      const result = await setComputerUsePaused(next)
      setPaused(result.paused)
      notify({
        kind: result.paused ? 'success' : 'warning',
        message: result.paused ? copy.pausedToast : copy.resumedToast
      })
    } catch (err) {
      notifyError(err, copy.toggleFailed)
    } finally {
      setPending(false)
    }
  }, [copy.pausedToast, copy.resumedToast, copy.toggleFailed, paused, pending])

  if (loading) {
    return (
      <div className="mt-3 flex items-center gap-2 rounded-lg border border-(--ui-stroke-tertiary) bg-background/55 px-3 py-2.5 text-xs text-muted-foreground">
        <Loader2 className="size-3.5 animate-spin" />
        {t.savings.cockpit.checking}
      </div>
    )
  }

  if (paused === null) {
    return null
  }

  return (
    <div className="mt-3 flex flex-wrap items-center justify-between gap-2.5 rounded-lg border border-(--ui-stroke-tertiary) bg-background/55 px-3 py-2.5">
      <div className="flex min-w-0 items-center gap-2">
        <Monitor className="size-4 shrink-0 text-muted-foreground" />
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-sm font-medium">{copy.title}</span>
            <Badge variant={paused ? 'muted' : 'warn'}>
              <span
                aria-hidden="true"
                className={cn('size-1.5 rounded-full', paused ? 'bg-muted-foreground/50' : 'animate-pulse bg-amber-500')}
              />
              {paused ? copy.pausedStatus : copy.activeStatus}
            </Badge>
          </div>
          <p className="mt-0.5 text-[0.7rem] text-muted-foreground">{paused ? copy.pausedHint : copy.activeHint}</p>
        </div>
      </div>
      <Button disabled={pending} onClick={() => void toggle()} size="sm" variant={paused ? 'default' : 'destructive'}>
        {pending ? (
          <Loader2 className="size-3.5 animate-spin" />
        ) : paused ? (
          <Play className="size-3.5" />
        ) : (
          <Pause className="size-3.5" />
        )}
        {paused ? copy.resumeAction : copy.pauseAction}
      </Button>
    </div>
  )
}
