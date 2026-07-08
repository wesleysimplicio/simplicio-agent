// Billing data contract. Shaped to match whatever a real Stripe-backed REST
// endpoint (`/api/billing/*`) would return, so billing-client.ts can try the
// real backend first and fall back to the local simulation in
// billing-simulated.ts without any UI code ever needing to change once the
// backend exists.

export interface BillingPlan {
  id: string
  /** Display name, e.g. "Plano Max". */
  name: string
  /** One-line tagline under the plan name, e.g. "20x mais uso que o Pro". */
  tagline: string
}

export type BillingSubscriptionStatus = 'active' | 'canceling' | 'canceled' | 'none'

export interface BillingSubscription {
  status: BillingSubscriptionStatus
  plan: BillingPlan | null
  /** ISO 8601 date. Set only when status === 'canceling' (end-of-period cutoff). */
  cancelAt: string | null
}

export interface BillingPaymentMethod {
  /** Display label, e.g. "Link by Stripe" or "Visa •••• 4242". */
  label: string
  kind: 'card' | 'link' | 'none'
}

export type BillingInvoiceStatus = 'open' | 'paid' | 'uncollectible' | 'void'

export interface BillingInvoice {
  id: string
  /** ISO 8601 date. */
  date: string
  /** Pre-formatted amount, e.g. "R$ 1.069,91" — currency formatting is owned by
   *  whichever source produced the record (mirrors how the rest of the app
   *  pre-formats money, e.g. the savings dashboard). */
  amountLabel: string
  status: BillingInvoiceStatus
  /** Hosted invoice URL, when available. Null in the simulation. */
  url: string | null
}

export interface BillingSummary {
  subscription: BillingSubscription
  paymentMethod: BillingPaymentMethod | null
  invoices: BillingInvoice[]
  /** Stripe customer-portal URL, when the backend provides one. Null in the simulation. */
  portalUrl: string | null
  /** True when this summary came from the local simulation, not a real backend. */
  simulated: boolean
}

export interface BillingActionResult {
  ok: boolean
  /** Portal/checkout URL to open, when the backend returns one. */
  url?: string | null
  simulated: boolean
}
