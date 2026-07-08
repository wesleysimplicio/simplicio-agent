// Billing client — tries a real backend endpoint first, falls back to the
// local simulation (billing-simulated.ts) when it doesn't exist yet (404 /
// network error / any failure). This is the whole point of the split: once a
// real `/api/billing/*` surface exists on the backend (Stripe-backed), this
// file starts returning `simulated: false` automatically and NOTHING in the
// UI (billing-settings.tsx) needs to change — same shape in, same shape out.
//
// Mirrors the profileScoped()/window.hermesDesktop.api<T>() pattern already
// used throughout src/hermes.ts (e.g. getComputerUseStatus()).

import {
  getSimulatedBillingSummary,
  simulateCancelSubscription,
  simulateChangePlan,
  simulateResubscribe,
  simulateUpdatePaymentMethod
} from './billing-simulated'
import type { BillingActionResult, BillingSummary } from './billing-types'

function profileScoped(): { profile?: string } {
  const params = new URLSearchParams(window.location.search)
  const profile = params.get('profile')
  return profile ? { profile } : {}
}

async function callBillingApi<T>(path: string, method: 'GET' | 'POST' = 'GET', body?: unknown): Promise<T> {
  const api = window.hermesDesktop?.api
  if (!api) {
    throw new Error('desktop bridge unavailable')
  }
  return api<T>({ ...profileScoped(), path, method, body })
}

export async function getBillingSummary(): Promise<BillingSummary> {
  try {
    return await callBillingApi<BillingSummary>('/api/billing/summary')
  } catch {
    // No backend endpoint yet (or it failed) — fall back to the local
    // simulation so the screen still renders something coherent.
    return getSimulatedBillingSummary()
  }
}

export async function requestChangePlan(): Promise<BillingActionResult> {
  try {
    return await callBillingApi<BillingActionResult>('/api/billing/portal', 'POST', { intent: 'change_plan' })
  } catch {
    return simulateChangePlan()
  }
}

export async function requestResubscribe(): Promise<BillingActionResult> {
  try {
    return await callBillingApi<BillingActionResult>('/api/billing/resubscribe', 'POST')
  } catch {
    return simulateResubscribe()
  }
}

export async function requestCancelSubscription(): Promise<BillingActionResult> {
  try {
    return await callBillingApi<BillingActionResult>('/api/billing/cancel', 'POST')
  } catch {
    return simulateCancelSubscription()
  }
}

export async function requestUpdatePaymentMethod(): Promise<BillingActionResult> {
  try {
    return await callBillingApi<BillingActionResult>('/api/billing/portal', 'POST', { intent: 'update_payment_method' })
  } catch {
    return simulateUpdatePaymentMethod()
  }
}
