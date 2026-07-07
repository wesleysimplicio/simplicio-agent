import type { SavingsEvent } from '@/app/savings/parse'
import { formatExactTokens, formatTimestamp } from '@/app/savings/format'
import { ProofBadge } from '@/components/savings/proof-badge'
import { useI18n } from '@/i18n'

interface SessionEventsTableProps {
  events: readonly SavingsEvent[]
}

// Per-event ledger table, newest first. Every numeric cell falls back to the
// literal "—" via the format helpers rather than a fabricated 0 — an absent
// field must read as absent, not as zero savings.
export function SessionEventsTable({ events }: SessionEventsTableProps) {
  const { t } = useI18n()
  const s = t.savings

  return (
    <div className="overflow-x-auto rounded-lg border border-(--ui-stroke-tertiary)">
      <table className="w-full min-w-[40rem] border-collapse text-[0.72rem]">
        <thead>
          <tr className="border-b border-(--ui-stroke-tertiary) text-left text-[0.6rem] uppercase tracking-wider text-muted-foreground/60">
            <th className="px-3 py-2 font-medium">{s.columnTimestamp}</th>
            <th className="px-3 py-2 font-medium">{s.columnContext}</th>
            <th className="px-3 py-2 text-right font-medium">{s.columnSpent}</th>
            <th className="px-3 py-2 text-right font-medium">{s.columnBaseline}</th>
            <th className="px-3 py-2 text-right font-medium">{s.columnSaved}</th>
            <th className="px-3 py-2 font-medium">{s.columnProof}</th>
          </tr>
        </thead>
        <tbody>
          {events.map((event, index) => {
            const context = [event.session, event.repo, event.model].filter(Boolean).join(' · ')

            return (
              <tr
                className="savings-stagger-in border-b border-(--ui-stroke-tertiary)/60 last:border-b-0 hover:bg-(--ui-row-hover-background)"
                key={event.id}
                style={{ animationDelay: `${Math.min(index, 12) * 24}ms` }}
              >
                <td className="whitespace-nowrap px-3 py-2 text-muted-foreground/80">
                  {formatTimestamp(event.timestamp)}
                </td>
                <td className="max-w-48 truncate px-3 py-2 font-mono text-[0.68rem] text-foreground/80" title={context}>
                  {context || s.unknownProofLabel}
                </td>
                <td className="whitespace-nowrap px-3 py-2 text-right tabular-nums">{formatExactTokens(event.spent)}</td>
                <td className="whitespace-nowrap px-3 py-2 text-right tabular-nums text-muted-foreground/70">
                  {formatExactTokens(event.baseline)}
                </td>
                <td className="whitespace-nowrap px-3 py-2 text-right font-medium tabular-nums text-emerald-500 dark:text-emerald-400">
                  {formatExactTokens(event.saved)}
                </td>
                <td className="px-3 py-2">
                  <ProofBadge proofKind={event.proofKind} />
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
