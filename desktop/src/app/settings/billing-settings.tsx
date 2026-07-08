import { useCallback, useEffect, useState } from 'react'

import { Button } from '@/components/ui/button'
import { useI18n } from '@/i18n'
import { Calendar, CreditCard, Crown, ExternalLink, FileText, Loader2 } from '@/lib/icons'
import { notify, notifyError } from '@/store/notifications'

import {
  getBillingSummary,
  requestChangePlan,
  requestResubscribe,
  requestUpdatePaymentMethod
} from './billing-client'
import type { BillingInvoice, BillingInvoiceStatus, BillingSummary } from './billing-types'
import { EmptyState, LoadingState, Pill, SectionHeading, SettingsContent } from './primitives'

function formatDate(iso: string): string {
  try {
    return new Intl.DateTimeFormat(undefined, { day: '2-digit', month: 'short', year: 'numeric' }).format(
      new Date(`${iso}T00:00:00`)
    )
  } catch {
    return iso
  }
}

type BillingCopy = ReturnType<typeof useI18n>['t']['settings']['billing']

function invoiceStatusLabel(status: BillingInvoiceStatus, s: BillingCopy): string {
  return s.invoiceStatus[status]
}

function invoiceStatusTone(status: BillingInvoiceStatus): 'muted' | 'primary' {
  return status === 'paid' ? 'primary' : 'muted'
}

// Which action button is currently in flight -- disables just that button
// (not the whole page) while a request/simulation round-trip is pending.
type BusyAction = 'changePlan' | 'resubscribe' | 'updatePaymentMethod' | null

export function BillingSettings() {
  const { t } = useI18n()
  const s = t.settings.billing
  const [summary, setSummary] = useState<BillingSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState<BusyAction>(null)

  const load = useCallback(async () => {
    setLoading(true)

    try {
      setSummary(await getBillingSummary())
    } catch (err) {
      notifyError(err, s.actionFailed)
    } finally {
      setLoading(false)
    }
  }, [s.actionFailed])

  useEffect(() => {
    void load()
  }, [load])

  const openIfUrl = (url: string | null | undefined) => {
    if (url) {
      window.open(url, '_blank', 'noopener,noreferrer')
    }
  }

  const changePlan = useCallback(async () => {
    setBusy('changePlan')

    try {
      const result = await requestChangePlan()
      if (result.simulated) {
        notify({ kind: 'info', message: s.changePlanSimulated })
      } else {
        openIfUrl(result.url)
      }
    } catch (err) {
      notifyError(err, s.actionFailed)
    } finally {
      setBusy(null)
    }
  }, [s])

  const resubscribe = useCallback(async () => {
    setBusy('resubscribe')

    try {
      const result = await requestResubscribe()
      if (result.simulated) {
        notify({ kind: 'success', message: s.resubscribeSuccess })
      }
      await load()
    } catch (err) {
      notifyError(err, s.actionFailed)
    } finally {
      setBusy(null)
    }
  }, [load, s])

  const updatePaymentMethod = useCallback(async () => {
    setBusy('updatePaymentMethod')

    try {
      const result = await requestUpdatePaymentMethod()
      if (result.simulated) {
        notify({ kind: 'info', message: s.paymentMethodUpdateSimulated })
      } else {
        openIfUrl(result.url)
      }
    } catch (err) {
      notifyError(err, s.actionFailed)
    } finally {
      setBusy(null)
    }
  }, [s])

  const viewInvoice = useCallback(
    (invoice: BillingInvoice) => {
      if (invoice.url) {
        window.open(invoice.url, '_blank', 'noopener,noreferrer')
        return
      }
      notify({ kind: 'info', message: s.invoiceViewSimulated(invoice.amountLabel, formatDate(invoice.date)) })
    },
    [s]
  )

  if (loading) {
    return <LoadingState label={s.loading} />
  }

  if (!summary) {
    return <EmptyState description={s.actionFailed} title={s.noneTitle} />
  }

  const { subscription, paymentMethod, invoices, simulated } = summary

  return (
    <SettingsContent>
      {simulated && (
        <div className="mb-4 rounded-lg border border-(--stroke-nous) bg-(--ui-bg-tertiary) p-3 text-[length:var(--conversation-caption-font-size)] text-(--ui-text-tertiary)">
          <Pill>{s.simulatedBadge}</Pill> <span className="ml-1.5">{s.simulatedNotice}</span>
        </div>
      )}

      {subscription.status === 'none' || !subscription.plan ? (
        <EmptyState description={s.noneDesc} title={s.noneTitle} />
      ) : (
        <>
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-(--stroke-nous) p-4">
            <div className="flex items-center gap-3">
              <div className="grid size-9 shrink-0 place-items-center rounded-full bg-(--ui-bg-tertiary)">
                <Crown className="size-4.5 text-muted-foreground" />
              </div>
              <div>
                <div className="text-[length:var(--conversation-text-font-size)] font-semibold">
                  {subscription.plan.name}
                </div>
                <div className="text-[length:var(--conversation-caption-font-size)] text-(--ui-text-tertiary)">
                  {subscription.plan.tagline}
                </div>
              </div>
            </div>
            <Button disabled={busy === 'changePlan'} onClick={() => void changePlan()} size="sm" variant="textStrong">
              {busy === 'changePlan' && <Loader2 className="size-3.5 animate-spin" />}
              {s.changePlan}
            </Button>
          </div>

          {subscription.status === 'canceling' && subscription.cancelAt && (
            <div className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-lg bg-(--ui-bg-tertiary) p-3">
              <div className="flex items-center gap-2 text-[length:var(--conversation-caption-font-size)]">
                <Calendar className="size-3.5 text-muted-foreground" />
                <span>{s.cancelSubscriptionBanner(formatDate(subscription.cancelAt))}</span>
              </div>
              <Button disabled={busy === 'resubscribe'} onClick={() => void resubscribe()} size="sm" variant="textStrong">
                {busy === 'resubscribe' && <Loader2 className="size-3.5 animate-spin" />}
                {s.resubscribe}
              </Button>
            </div>
          )}
        </>
      )}

      <SectionHeading icon={CreditCard} title={s.paymentTitle} />
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-(--stroke-nous) p-3">
        <div className="flex items-center gap-2.5">
          <CreditCard className="size-4 text-muted-foreground" />
          <span className="text-[length:var(--conversation-text-font-size)]">
            {paymentMethod?.label ?? s.noPaymentMethod}
          </span>
        </div>
        <Button
          disabled={busy === 'updatePaymentMethod'}
          onClick={() => void updatePaymentMethod()}
          size="sm"
          variant="textStrong"
        >
          {busy === 'updatePaymentMethod' && <Loader2 className="size-3.5 animate-spin" />}
          {s.updatePaymentMethod}
        </Button>
      </div>

      <SectionHeading icon={FileText} meta={invoices.length ? String(invoices.length) : undefined} title={s.invoicesTitle} />
      {invoices.length === 0 ? (
        <EmptyState description="" title={s.invoicesEmpty} />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-[length:var(--conversation-caption-font-size)]">
            <thead>
              <tr className="border-b border-(--stroke-nous) text-left text-(--ui-text-tertiary)">
                <th className="py-2 pr-4 font-medium">{s.invoiceDateHeader}</th>
                <th className="py-2 pr-4 font-medium">{s.invoiceTotalHeader}</th>
                <th className="py-2 pr-4 font-medium">{s.invoiceStatusHeader}</th>
                <th className="py-2 pr-4 font-medium">{s.invoiceActionsHeader}</th>
              </tr>
            </thead>
            <tbody>
              {invoices.map(invoice => (
                <tr className="border-b border-(--stroke-nous)/50" key={invoice.id}>
                  <td className="py-2.5 pr-4">{formatDate(invoice.date)}</td>
                  <td className="py-2.5 pr-4">{invoice.amountLabel}</td>
                  <td className="py-2.5 pr-4">
                    <Pill tone={invoiceStatusTone(invoice.status)}>{invoiceStatusLabel(invoice.status, s)}</Pill>
                  </td>
                  <td className="py-2.5 pr-4">
                    <button
                      className="inline-flex items-center gap-1 text-primary hover:underline"
                      onClick={() => viewInvoice(invoice)}
                      type="button"
                    >
                      {s.invoiceView}
                      {invoice.url && <ExternalLink className="size-3" />}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </SettingsContent>
  )
}
