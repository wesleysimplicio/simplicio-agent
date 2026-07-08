// Local simulation of the billing backend. Used by billing-client.ts as the
// fallback when no real `/api/billing/*` endpoint exists yet (see that
// file's header). Everything here is clearly a stand-in: state persists in
// localStorage so a user testing the screen sees consistent behaviour across
// reloads, but no real Stripe call is ever made.

import type {
  BillingActionResult,
  BillingInvoice,
  BillingPlan,
  BillingSubscription,
  BillingSummary
} from './billing-types'

const STORAGE_KEY = 'simplicio.billing.simulated.v1'

const MAX_PLAN: BillingPlan = {
  id: 'max',
  name: 'Plano Max',
  tagline: '20x mais uso que o Pro'
}

function seedInvoices(): BillingInvoice[] {
  return [
    { id: 'inv_sim_1', date: '2026-06-10', amountLabel: 'R$ 1.069,91', status: 'paid', url: null },
    { id: 'inv_sim_2', date: '2026-05-12', amountLabel: 'R$ 550,00', status: 'paid', url: null },
    { id: 'inv_sim_3', date: '2026-04-12', amountLabel: 'R$ 573,06', status: 'paid', url: null },
    { id: 'inv_sim_4', date: '2026-04-10', amountLabel: 'R$ 443,64', status: 'paid', url: null },
    { id: 'inv_sim_5', date: '2026-04-09', amountLabel: 'R$ 110,00', status: 'paid', url: null }
  ]
}

interface SimulatedState {
  subscription: BillingSubscription
  paymentMethodLabel: string
  invoices: BillingInvoice[]
}

function defaultState(): SimulatedState {
  return {
    subscription: { status: 'canceling', plan: MAX_PLAN, cancelAt: '2026-07-10' },
    paymentMethodLabel: 'Link by Stripe',
    invoices: seedInvoices()
  }
}

function loadState(): SimulatedState {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return defaultState()
    const parsed = JSON.parse(raw) as Partial<SimulatedState>
    return {
      subscription: parsed.subscription ?? defaultState().subscription,
      paymentMethodLabel: parsed.paymentMethodLabel ?? defaultState().paymentMethodLabel,
      invoices: parsed.invoices ?? defaultState().invoices
    }
  } catch {
    return defaultState()
  }
}

function saveState(state: SimulatedState): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state))
  } catch {
    // best-effort — simulation still works in-memory for this session
  }
}

export function getSimulatedBillingSummary(): BillingSummary {
  const state = loadState()
  return {
    subscription: state.subscription,
    paymentMethod: state.paymentMethodLabel ? { label: state.paymentMethodLabel, kind: 'link' } : null,
    invoices: state.invoices,
    portalUrl: null,
    simulated: true
  }
}

export function simulateResubscribe(): BillingActionResult {
  const state = loadState()
  state.subscription = { ...state.subscription, status: 'active', cancelAt: null }
  saveState(state)
  return { ok: true, url: null, simulated: true }
}

export function simulateCancelSubscription(): BillingActionResult {
  const state = loadState()
  const cancelAt = new Date()
  cancelAt.setMonth(cancelAt.getMonth() + 1)
  state.subscription = { ...state.subscription, status: 'canceling', cancelAt: cancelAt.toISOString().slice(0, 10) }
  saveState(state)
  return { ok: true, url: null, simulated: true }
}

export function simulateChangePlan(): BillingActionResult {
  // No real plan picker in the simulation — this is the seam a real
  // implementation would replace with a Stripe customer-portal redirect.
  return { ok: true, url: null, simulated: true }
}

export function simulateUpdatePaymentMethod(): BillingActionResult {
  return { ok: true, url: null, simulated: true }
}

export function resetSimulatedBilling(): void {
  try {
    localStorage.removeItem(STORAGE_KEY)
  } catch {
    // ignore
  }
}
