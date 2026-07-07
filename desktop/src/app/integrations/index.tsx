import type * as React from 'react'
import { useEffect, useRef, useState } from 'react'

import { Button } from '@/components/ui/button'
import { Codicon } from '@/components/ui/codicon'
import { type Translations, useI18n } from '@/i18n'
import { cn } from '@/lib/utils'
import { notify } from '@/store/notifications'

import { useRefreshHotkey } from '../hooks/use-refresh-hotkey'
import { PAGE_INSET_X } from '../layout-constants'
import type { SetStatusbarItemGroup } from '../shell/statusbar-controls'

import { DaemonCard } from './daemon-card'
import { EditorCard } from './editor-card'
import { sortEditorsForDisplay } from './editor-presentation'
import { DEPLOY_BACKEND_UNAVAILABLE, type DeployOutcome, useIntegrationsData } from './use-integrations-data'

interface IntegrationsViewProps extends React.ComponentProps<'section'> {
  setStatusbarItemGroup?: SetStatusbarItemGroup
}

export function IntegrationsView({ setStatusbarItemGroup: _setStatusbarItemGroup, ...props }: IntegrationsViewProps) {
  const { t } = useI18n()
  const c = t.integrations
  const { apiAvailable, daemonStatus, deploy, deployOutcome, deploying, detectError, editors, loading, refresh } =
    useIntegrationsData()

  useRefreshHotkey(() => void refresh())

  // Cascade-in the editor grid once, on first paint of a populated list —
  // never replays on a background poll refresh (`entered` only ever flips
  // true -> stays true), so re-fetching status doesn't re-trigger the animation.
  const [entered, setEntered] = useState(false)

  useEffect(() => {
    if (entered || !editors) {
      return
    }

    const frame = window.requestAnimationFrame(() => setEntered(true))

    return () => window.cancelAnimationFrame(frame)
  }, [editors, entered])

  // Toast once per completed deploy attempt (result object identity changes
  // exactly once per `deploy()` call), independent of the always-visible
  // inline result panel below the button.
  const lastOutcomeRef = useRef<DeployOutcome | null>(null)

  useEffect(() => {
    if (deployOutcome === lastOutcomeRef.current) {
      return
    }

    lastOutcomeRef.current = deployOutcome

    if (!deployOutcome) {
      return
    }

    if (deployOutcome.error) {
      notify({
        kind: 'error',
        title: c.deployFailedTitle,
        message: deployOutcome.error === DEPLOY_BACKEND_UNAVAILABLE ? c.backendUnavailable : deployOutcome.error
      })
    } else {
      notify({
        kind: 'success',
        title: c.deployedTitle,
        message: c.deployedSummary(deployOutcome.registered.length, deployOutcome.skipped.length)
      })
    }
  }, [deployOutcome, c])

  const sortedEditors = editors ? sortEditorsForDisplay(editors) : null

  return (
    <section
      {...props}
      className={cn(
        'flex h-full min-w-0 flex-col overflow-hidden bg-(--ui-chat-surface-background)',
        props.className
      )}
    >
      <div className={cn('shrink-0 pb-2 pt-[calc(var(--titlebar-height)+0.75rem)]', PAGE_INSET_X)}>
        <div className="flex items-center justify-between gap-3">
          <div className="min-w-0">
            <h1 className="text-sm font-semibold text-foreground">{c.title}</h1>
            <p className="mt-0.5 text-xs text-muted-foreground">{c.subtitle}</p>
          </div>
          <Button
            aria-label={loading ? t.common.loading : t.common.refresh}
            disabled={loading}
            onClick={() => void refresh()}
            size="icon-xs"
            title={loading ? t.common.loading : t.common.refresh}
            type="button"
            variant="ghost"
          >
            <Codicon name="refresh" size="0.875rem" spinning={loading} />
          </Button>
        </div>
      </div>

      <div className={cn('min-h-0 flex-1 overflow-y-auto pb-8', PAGE_INSET_X)}>
        {!apiAvailable ? (
          <BackendUnavailableNotice message={c.backendUnavailable} />
        ) : (
          <div className="grid gap-4">
            <DaemonCard copy={c} status={daemonStatus} />

            <div>
              <div className="mb-2 flex items-center justify-between gap-3">
                <h2 className="text-xs font-semibold uppercase tracking-[0.08em] text-muted-foreground">
                  {c.editorsHeading}
                </h2>
                <Button disabled={deploying || loading} onClick={() => void deploy()} size="sm">
                  {deploying ? c.deploying : c.deployAll}
                </Button>
              </div>

              {detectError && (
                <InlineNotice label={c.detectFailedTitle} message={detectError} tone="bad" />
              )}

              {!sortedEditors ? (
                <EditorGridSkeleton />
              ) : sortedEditors.length === 0 ? (
                <p className="text-xs text-muted-foreground">{c.noEditorsFound}</p>
              ) : (
                <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
                  {sortedEditors.map((editor, index) => (
                    <EditorCard copy={c} editor={editor} entered={entered} index={index} key={editor.id} />
                  ))}
                </div>
              )}

              {deployOutcome && (
                <DeployResultPanel copy={c} outcome={deployOutcome} />
              )}
            </div>
          </div>
        )}
      </div>
    </section>
  )
}

function BackendUnavailableNotice({ message }: { message: string }) {
  return (
    <div className="grid min-h-52 place-items-center text-center">
      <div className="max-w-sm">
        <Codicon aria-hidden className="text-2xl text-muted-foreground" name="debug-disconnect" />
        <p className="mt-2 text-sm text-muted-foreground">{message}</p>
      </div>
    </div>
  )
}

function InlineNotice({ label, message, tone }: { label: string; message: string; tone: 'bad' | 'warn' }) {
  return (
    <div
      className={cn(
        'mb-3 rounded-md border px-3 py-2 text-xs',
        tone === 'bad'
          ? 'border-destructive/30 bg-destructive/5 text-destructive'
          : 'border-amber-500/30 bg-amber-500/5 text-amber-600 dark:text-amber-300'
      )}
    >
      <span className="font-medium">{label}: </span>
      {message}
    </div>
  )
}

function EditorGridSkeleton() {
  return (
    <div aria-hidden="true" className="grid grid-cols-1 gap-2.5 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
      {Array.from({ length: 8 }, (_, index) => (
        <div
          className={cn(
            'h-[4.5rem] animate-pulse rounded-[10px] border border-(--ui-stroke-secondary)',
            'bg-(--ui-bg-secondary) motion-reduce:animate-none'
          )}
          key={index}
        />
      ))}
    </div>
  )
}

function DeployResultPanel({ copy, outcome }: { copy: Translations['integrations']; outcome: DeployOutcome }) {
  if (outcome.error) {
    return (
      <InlineNotice
        label={copy.deployFailedTitle}
        message={outcome.error === DEPLOY_BACKEND_UNAVAILABLE ? copy.backendUnavailable : outcome.error}
        tone="bad"
      />
    )
  }

  return (
    <div
      className={cn(
        'mt-3 grid gap-2 rounded-md border border-(--ui-stroke-secondary) bg-(--ui-bg-secondary)',
        'px-3 py-2.5 text-xs'
      )}
    >
      <div className="text-muted-foreground">
        <span className="font-medium text-foreground">{copy.deployResultRegisteredLabel}</span>{' '}
        {outcome.registered.length === 0 ? copy.deployResultNoneRegistered : outcome.registered.join(', ')}
      </div>
      {outcome.skipped.length > 0 && (
        <div className="text-muted-foreground">
          <span className="font-medium text-foreground">{copy.deployResultSkippedLabel}</span>{' '}
          {outcome.skipped.join(', ')}
        </div>
      )}
      <div className="text-(--ui-text-quaternary)">{copy.restartNote}</div>
    </div>
  )
}
