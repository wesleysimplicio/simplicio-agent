import { beforeEach, describe, expect, it } from 'vitest'

import {
  getSimulatedBillingSummary,
  resetSimulatedBilling,
  simulateCancelSubscription,
  simulateResubscribe
} from './billing-simulated'

describe('billing-simulated', () => {
  beforeEach(() => {
    resetSimulatedBilling()
  })

  it('seeds a canceling Max plan with invoices and a payment method', () => {
    const summary = getSimulatedBillingSummary()

    expect(summary.simulated).toBe(true)
    expect(summary.subscription.status).toBe('canceling')
    expect(summary.subscription.plan?.name).toBe('Plano Max')
    expect(summary.subscription.cancelAt).toBeTruthy()
    expect(summary.paymentMethod?.label).toBe('Link by Stripe')
    expect(summary.invoices.length).toBeGreaterThan(0)
    expect(summary.invoices.every(inv => inv.status === 'paid')).toBe(true)
  })

  it('resubscribe clears cancelAt and flips status to active, persisted across reads', () => {
    const result = simulateResubscribe()
    expect(result.ok).toBe(true)
    expect(result.simulated).toBe(true)

    const summary = getSimulatedBillingSummary()
    expect(summary.subscription.status).toBe('active')
    expect(summary.subscription.cancelAt).toBeNull()
  })

  it('cancelSubscription sets status to canceling with a future cancelAt date', () => {
    simulateResubscribe()
    const result = simulateCancelSubscription()
    expect(result.ok).toBe(true)

    const summary = getSimulatedBillingSummary()
    expect(summary.subscription.status).toBe('canceling')
    expect(summary.subscription.cancelAt).toBeTruthy()
    expect(new Date(summary.subscription.cancelAt as string).getTime()).toBeGreaterThan(Date.now())
  })

  it('state persists across independent reads until reset', () => {
    simulateResubscribe()
    expect(getSimulatedBillingSummary().subscription.status).toBe('active')
    expect(getSimulatedBillingSummary().subscription.status).toBe('active')

    resetSimulatedBilling()
    expect(getSimulatedBillingSummary().subscription.status).toBe('canceling')
  })
})
