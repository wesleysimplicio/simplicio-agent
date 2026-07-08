import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { BillingSettings } from './billing-settings'
import { resetSimulatedBilling } from './billing-simulated'

// No window.hermesDesktop in jsdom -> billing-client.ts's try/catch naturally
// falls back to the local simulation, exactly like a real desktop build would
// until a `/api/billing/*` backend endpoint exists.

describe('BillingSettings', () => {
  beforeEach(() => {
    resetSimulatedBilling()
  })

  afterEach(() => {
    cleanup()
  })

  it('renders the simulated Max plan, cancellation banner, payment method, and invoices', async () => {
    render(<BillingSettings />)

    expect(await screen.findByText('Plano Max')).toBeTruthy()

    expect(screen.getByText('20x mais uso que o Pro')).toBeTruthy()
    expect(screen.getByText('Link by Stripe')).toBeTruthy()
    expect(screen.getAllByText('R$ 1.069,91').length).toBeGreaterThan(0)
    // i18n strings render in the test env's default locale (English) --
    // "Plano Max" / "Link by Stripe" / "R$ 1.069,91" above are untranslated
    // literal seed data from billing-simulated.ts, not i18n keys.
    expect(screen.getAllByText('View').length).toBeGreaterThan(0)
  })
})
