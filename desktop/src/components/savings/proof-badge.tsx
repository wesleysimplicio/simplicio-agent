import type { ProofKind } from '@/app/savings/types'
import { Tip } from '@/components/ui/tooltip'
import { useI18n } from '@/i18n'
import { CheckCircle2, HelpCircle } from '@/lib/icons'
import { cn } from '@/lib/utils'

interface ProofBadgeProps {
  className?: string
  proofKind: null | ProofKind
}

// The honesty ladder — measured > replayed > benchmark > estimated — is the
// panel's entire evidence contract — always visible, never collapsed into a
// generic "OK" pill. `measured` = a real provider/ledger receipt for this
// exact run; `replayed` = this session's own recorded trace replayed
// deterministically (real but not live); `benchmark` = an offline reference
// run standing in for this session's real usage; `estimated` = a heuristic
// guess; unknown (no proof_kind on the record) renders its own neutral badge
// rather than defaulting to any of the above.
//
// `replayed`/`benchmark` are net-new evidence tiers (issue #128) added
// alongside the already-localized measured/estimated pair; their labels are
// intentionally plain English literals here rather than new `t.savings.*`
// keys — adding mandatory keys to `Translations` would require touching
// every one of the ~16 locale catalogs for two evidence tiers most reports
// never produce. Revisit if/when they need full localization.
export function ProofBadge({ className, proofKind }: ProofBadgeProps) {
  const { t } = useI18n()
  const s = t.savings

  if (proofKind === 'measured') {
    return (
      <Tip label={s.measuredTooltip}>
        <span
          className={cn(
            'inline-flex items-center gap-1 rounded-full bg-emerald-500/15 px-1.5 py-0.5 text-[0.62rem] font-medium text-emerald-500 dark:text-emerald-400',
            className
          )}
        >
          <CheckCircle2 className="size-3" />
          {s.measuredLabel}
        </span>
      </Tip>
    )
  }

  if (proofKind === 'replayed') {
    return (
      <Tip label="This session's own recorded trace, replayed deterministically.">
        <span
          className={cn(
            'inline-flex items-center gap-1 rounded-full bg-sky-500/15 px-1.5 py-0.5 text-[0.62rem] font-medium text-sky-500 dark:text-sky-400',
            className
          )}
        >
          <CheckCircle2 className="size-3" />
          Replayed
        </span>
      </Tip>
    )
  }

  if (proofKind === 'benchmark') {
    return (
      <Tip label="Offline reference run, not this session's live usage.">
        <span
          className={cn(
            'inline-flex items-center gap-1 rounded-full border border-violet-500/50 px-1.5 py-0.5 text-[0.62rem] font-medium text-violet-600 dark:text-violet-400',
            className
          )}
        >
          <HelpCircle className="size-3" />
          Benchmark
        </span>
      </Tip>
    )
  }

  if (proofKind === 'estimated') {
    return (
      <Tip label={s.estimatedTooltip}>
        <span
          className={cn(
            'inline-flex items-center gap-1 rounded-full border border-amber-500/50 px-1.5 py-0.5 text-[0.62rem] font-medium text-amber-600 dark:text-amber-400',
            className
          )}
        >
          <HelpCircle className="size-3" />
          {s.estimatedLabel}
        </span>
      </Tip>
    )
  }

  return (
    <Tip label={s.unknownProofTooltip}>
      <span
        className={cn(
          'inline-flex items-center gap-1 rounded-full bg-foreground/8 px-1.5 py-0.5 text-[0.62rem] font-medium text-muted-foreground',
          className
        )}
      >
        {s.unknownProofLabel}
      </span>
    </Tip>
  )
}
