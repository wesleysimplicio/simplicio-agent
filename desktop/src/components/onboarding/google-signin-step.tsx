import { useEffect, useRef, useState } from 'react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Loader2 } from '@/lib/icons'
import { setGoogleSignedIn } from '@/store/onboarding'

import { Step } from './flow'

const SIMULATED_EMAIL = 'voce@exemplo.com'
const SIMULATED_SIGNIN_MS = 1200

// Step B: "Entrar com Google (simulado)". Real Google OAuth is intentionally
// NOT implemented here — this is a UI-only step for exercising the
// onboarding flow end-to-end. No network call is made; the "MODO TESTE"
// badge stays visible at all times so the simulated sign-in is never
// mistaken for a real one. Skippable and non-blocking.
export function GoogleSignInStep({ onContinue }: { onContinue: () => void }) {
  const [signingIn, setSigningIn] = useState(false)
  const [signedIn, setSignedIn] = useState(false)
  const signInTimer = useRef<number | null>(null)

  // If the user skips (unmounting this step) while the simulated sign-in is
  // still pending, the timer must die with the component — otherwise it
  // would record a signed-in state the user explicitly walked away from.
  useEffect(
    () => () => {
      if (signInTimer.current !== null) {
        window.clearTimeout(signInTimer.current)
      }
    },
    [],
  )

  const handleSignIn = () => {
    if (signingIn || signedIn) {
      return
    }

    setSigningIn(true)
    signInTimer.current = window.setTimeout(() => {
      signInTimer.current = null
      setSigningIn(false)
      setSignedIn(true)
      setGoogleSignedIn(SIMULATED_EMAIL)
    }, SIMULATED_SIGNIN_MS)
  }

  return (
    <Step title="Entrar com Google (simulado)">
      <div className="grid gap-3 rounded-xl border border-(--stroke-nous) p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span className="text-sm font-semibold">Conta Google</span>
          <Badge variant="warn">MODO TESTE — login simulado</Badge>
        </div>
        <p className="text-xs leading-5 text-muted-foreground">
          Este passo simula um login com Google para testar o fluxo de onboarding. Nenhuma autenticação real
          acontece e nenhuma chamada de rede é feita.
        </p>
        <Button
          className="justify-center"
          disabled={signingIn}
          onClick={handleSignIn}
          size="lg"
          variant={signedIn ? 'secondary' : 'outline'}
        >
          {signingIn ? <Loader2 className="size-4 animate-spin" /> : <GoogleGlyph />}
          {signingIn ? 'Entrando...' : signedIn ? `${SIMULATED_EMAIL} · simulado` : 'Continuar com Google'}
        </Button>
      </div>

      <div className="flex items-center justify-end gap-3 pt-1">
        <Button onClick={onContinue} size="sm" variant="text">
          Pular
        </Button>
        <Button disabled={signingIn} onClick={onContinue} size="sm">
          Continuar
        </Button>
      </div>
    </Step>
  )
}

// Minimal inline "G" glyph so the button reads as an OAuth-style provider
// button without pulling in a brand icon asset/dependency.
function GoogleGlyph() {
  return (
    <svg aria-hidden="true" className="size-4 shrink-0" viewBox="0 0 24 24">
      <path
        d="M21.6 12.23c0-.68-.06-1.36-.19-2H12v3.79h5.4a4.6 4.6 0 0 1-2 3.02v2.5h3.23c1.9-1.75 2.97-4.34 2.97-7.31Z"
        fill="#4285F4"
      />
      <path
        d="M12 22c2.7 0 4.97-.89 6.63-2.42l-3.23-2.5c-.9.6-2.06.96-3.4.96-2.6 0-4.8-1.76-5.6-4.12H3.06v2.58A10 10 0 0 0 12 22Z"
        fill="#34A853"
      />
      <path d="M6.4 13.92a5.99 5.99 0 0 1 0-3.84V7.5H3.06a10 10 0 0 0 0 9l3.34-2.58Z" fill="#FBBC05" />
      <path
        d="M12 6.04c1.47 0 2.79.5 3.83 1.5l2.87-2.87A9.96 9.96 0 0 0 12 2a10 10 0 0 0-8.94 5.5l3.34 2.58c.8-2.36 3-4.04 5.6-4.04Z"
        fill="#EA4335"
      />
    </svg>
  )
}
