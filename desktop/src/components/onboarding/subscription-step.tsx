import { useState } from 'react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Check } from '@/lib/icons'
import { setSubscribed } from '@/store/onboarding'

import { Step } from './flow'

const BENEFITS = [
  'Economia de tokens monitorada em tempo real',
  'MCP sempre ativo, sem configuração extra',
  'Integrações com editores (Zed, VS Code, JetBrains)'
]

// Step C: "Assinatura (simulada)". Billing is intentionally NOT wired up —
// this is a UI-only simulation so the onboarding flow can be exercised
// end-to-end. The gate is OFF: nothing in the app checks `subscribed`
// (see store/onboarding.ts setSubscribed), so skipping never blocks usage.
// Either action finishes the whole onboarding sequence.
export function SubscriptionStep({ onFinish }: { onFinish: () => void }) {
  const [subscribed, setLocalSubscribed] = useState(false)

  const subscribe = () => {
    setLocalSubscribed(true)
    setSubscribed(true)
    onFinish()
  }

  return (
    <Step title="Assinatura (simulada)">
      <div className="grid gap-3 rounded-xl border border-(--stroke-nous) p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span className="text-sm font-semibold">Simplicio Pro</span>
          <span className="font-mono text-xs text-muted-foreground">US$ 19/mês (exemplo)</span>
        </div>
        <ul className="grid gap-1.5">
          {BENEFITS.map(benefit => (
            <li className="flex items-start gap-2 text-xs leading-5 text-muted-foreground" key={benefit}>
              <Check className="mt-0.5 size-3.5 shrink-0 text-primary" />
              {benefit}
            </li>
          ))}
        </ul>
        <Badge className="w-fit" variant="warn">
          SIMULAÇÃO — nenhuma cobrança real
        </Badge>
        <Button className="justify-center" disabled={subscribed} onClick={subscribe} size="lg">
          Assinar (simulação)
        </Button>
      </div>

      <div className="flex justify-end pt-1">
        <Button onClick={onFinish} size="sm" variant="text">
          Continuar sem assinar
        </Button>
      </div>
    </Step>
  )
}
