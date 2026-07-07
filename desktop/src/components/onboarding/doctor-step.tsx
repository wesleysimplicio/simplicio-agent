import { useEffect, useState } from 'react'

import { Button } from '@/components/ui/button'
import { AlertCircle, AlertTriangle, CheckCircle2, HelpCircle, Loader2, RefreshCw, type IconComponent } from '@/lib/icons'
import { cn } from '@/lib/utils'

import { mapDoctorToChecklist, type DoctorChecklistItem, type DoctorItemStatus } from './doctor-checklist'
import { Step } from './flow'

// ---------------------------------------------------------------------------
// Local bridge contract
// ---------------------------------------------------------------------------
// `window.simplicioSavings.doctorRun()` is being wired into the Electron
// preload by a parallel change (see desktop/electron/, out of this step's
// scope). We declare the contract locally instead of touching global.d.ts —
// which that other change owns — and guard every access: the bridge may not
// exist yet on a given build, and this step must never block onboarding when
// it doesn't.

interface DoctorRunOk {
  doctor: unknown
  ok: true
}

interface DoctorRunErr {
  error: string
  ok: false
}

type DoctorRunResult = DoctorRunOk | DoctorRunErr

interface SimplicioSavingsBridge {
  doctorRun: () => Promise<DoctorRunResult>
}

function getSimplicioSavingsBridge(): SimplicioSavingsBridge | undefined {
  const bridge = (window as unknown as { simplicioSavings?: Partial<SimplicioSavingsBridge> }).simplicioSavings

  return typeof bridge?.doctorRun === 'function' ? (bridge as SimplicioSavingsBridge) : undefined
}

type LoadState =
  | { kind: 'error'; message: string }
  | { items: DoctorChecklistItem[]; kind: 'ready' }
  | { kind: 'loading' }
  | { kind: 'unavailable' }

async function runDoctor(): Promise<LoadState> {
  const bridge = getSimplicioSavingsBridge()

  if (!bridge) {
    return { kind: 'unavailable' }
  }

  try {
    const result = await bridge.doctorRun()

    if (!result.ok) {
      return { kind: 'error', message: result.error || 'Falha desconhecida ao rodar o doctor.' }
    }

    return { kind: 'ready', items: mapDoctorToChecklist(result.doctor) }
  } catch (error) {
    return { kind: 'error', message: error instanceof Error ? error.message : String(error) }
  }
}

// Step A: "Pendências do runtime". Skippable and non-blocking — the
// "Continuar" button is always enabled regardless of what the doctor
// reports; this is a diagnostic surface, not a gate.
export function DoctorStep({ onContinue }: { onContinue: () => void }) {
  const [state, setState] = useState<LoadState>({ kind: 'loading' })
  const [refreshing, setRefreshing] = useState(false)

  useEffect(() => {
    let cancelled = false

    void runDoctor().then(next => {
      if (!cancelled) {
        setState(next)
      }
    })

    return () => {
      cancelled = true
    }
  }, [])

  const recheck = async () => {
    setRefreshing(true)
    const next = await runDoctor()

    setRefreshing(false)
    setState(next)
  }

  return (
    <Step title="Pendências do runtime">
      <p className="text-sm text-muted-foreground">
        Verificação rápida do runtime Simplicio antes de começar — nada aqui bloqueia o uso do app.
      </p>

      {state.kind === 'loading' ? <DoctorLoading /> : null}
      {state.kind === 'unavailable' ? (
        <DoctorNotice text="Backend indisponível — a verificação de pendências ainda não está exposta nesta build." />
      ) : null}
      {state.kind === 'error' ? (
        <DoctorNotice text={`Não foi possível rodar o diagnóstico: ${state.message}`} />
      ) : null}
      {state.kind === 'ready' ? <DoctorChecklist items={state.items} /> : null}

      <div className="flex items-center justify-between gap-3 pt-1">
        <Button
          disabled={refreshing || state.kind === 'loading'}
          onClick={() => void recheck()}
          size="sm"
          variant="outline"
        >
          {refreshing ? <Loader2 className="size-3.5 animate-spin" /> : <RefreshCw className="size-3.5" />}
          Verificar novamente
        </Button>
        <Button onClick={onContinue} size="sm">
          Continuar
        </Button>
      </div>
    </Step>
  )
}

function DoctorLoading() {
  return (
    <div className="flex items-center gap-2.5 py-2 text-sm text-muted-foreground" role="status">
      <Loader2 className="size-4 animate-spin" />
      Rodando diagnóstico...
    </div>
  )
}

function DoctorNotice({ text }: { text: string }) {
  return (
    <p
      className="rounded-lg border border-(--ui-stroke-tertiary) bg-(--ui-bg-tertiary)/40 px-3 py-2.5 text-xs text-muted-foreground"
      role="status"
    >
      {text}
    </p>
  )
}

const STATUS_ICON: Record<DoctorItemStatus, IconComponent> = {
  ok: CheckCircle2,
  warning: AlertTriangle,
  error: AlertCircle,
  unknown: HelpCircle
}

const STATUS_CLASS: Record<DoctorItemStatus, string> = {
  ok: 'text-emerald-500 dark:text-emerald-400',
  warning: 'text-amber-500 dark:text-amber-400',
  error: 'text-destructive',
  unknown: 'text-muted-foreground'
}

function DoctorChecklist({ items }: { items: DoctorChecklistItem[] }) {
  if (items.length === 0) {
    return <DoctorNotice text="O diagnóstico não retornou itens." />
  }

  return (
    <ul className="grid gap-1.5">
      {items.map((item, index) => (
        <DoctorChecklistRow index={index} item={item} key={item.id} />
      ))}
    </ul>
  )
}

// Staggered fade+rise entrance per row, respecting prefers-reduced-motion
// (settles instantly instead of animating). No animation library — mirrors
// the matchMedia-guard pattern already used across this overlay.
function DoctorChecklistRow({ index, item }: { index: number; item: DoctorChecklistItem }) {
  const [mounted, setMounted] = useState(
    () => typeof window === 'undefined' || (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false)
  )
  const Icon = STATUS_ICON[item.status]

  useEffect(() => {
    if (mounted) {
      return
    }

    const id = window.setTimeout(() => setMounted(true), 40 + index * 60)

    return () => window.clearTimeout(id)
  }, [index, mounted])

  return (
    <li
      className={cn(
        'flex items-start gap-2.5 rounded-lg border border-(--ui-stroke-tertiary) px-3 py-2 transition-all duration-300 ease-out',
        mounted ? 'translate-y-0 opacity-100' : 'translate-y-1 opacity-0'
      )}
    >
      <Icon className={cn('mt-0.5 size-4 shrink-0', STATUS_CLASS[item.status])} />
      <div className="grid min-w-0 gap-0.5">
        <p className="text-sm font-medium leading-5">{item.title}</p>
        <p className="text-xs leading-5 text-muted-foreground" title={item.detail}>
          {item.detail}
        </p>
        {item.fixHint ? <p className="text-xs leading-5 text-amber-600 dark:text-amber-400">{item.fixHint}</p> : null}
      </div>
    </li>
  )
}
