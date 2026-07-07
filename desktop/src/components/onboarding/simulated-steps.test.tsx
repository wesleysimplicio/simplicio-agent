import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { $desktopOnboarding, DEFAULT_POST_SETUP_STATE } from '@/store/onboarding'

import { GoogleSignInStep } from './google-signin-step'
import { SubscriptionStep } from './subscription-step'

function resetPostSetup() {
  $desktopOnboarding.set({
    ...$desktopOnboarding.get(),
    postSetup: DEFAULT_POST_SETUP_STATE
  })
}

beforeEach(() => {
  vi.useFakeTimers()
  resetPostSetup()
})

afterEach(() => {
  cleanup()
  vi.useRealTimers()
  resetPostSetup()
})

describe('GoogleSignInStep (simulated)', () => {
  it('shows the MODO TESTE badge at all times, before any interaction', () => {
    render(<GoogleSignInStep onContinue={() => {}} />)

    expect(screen.getByText(/MODO TESTE/)).toBeTruthy()
  })

  it('records the simulated sign-in only after the delay completes', () => {
    render(<GoogleSignInStep onContinue={() => {}} />)

    fireEvent.click(screen.getByRole('button', { name: /Continuar com Google/ }))
    expect($desktopOnboarding.get().postSetup?.google.signedIn).toBe(false)

    vi.advanceTimersByTime(1300)
    expect($desktopOnboarding.get().postSetup?.google.signedIn).toBe(true)
  })

  it('never blocks: skip stays clickable during the simulated sign-in', () => {
    const onContinue = vi.fn()
    render(<GoogleSignInStep onContinue={onContinue} />)

    fireEvent.click(screen.getByRole('button', { name: /Continuar com Google/ }))
    fireEvent.click(screen.getByRole('button', { name: 'Pular' }))

    expect(onContinue).toHaveBeenCalledTimes(1)
  })

  it('does NOT record a sign-in when the user skips mid-flight (unmount cancels the timer)', () => {
    const { unmount } = render(<GoogleSignInStep onContinue={() => {}} />)

    fireEvent.click(screen.getByRole('button', { name: /Continuar com Google/ }))
    unmount() // user skipped away while the 1200ms simulation was pending

    vi.advanceTimersByTime(5000)
    expect($desktopOnboarding.get().postSetup?.google.signedIn).toBe(false)
  })
})

describe('SubscriptionStep (simulated)', () => {
  it('shows the SIMULAÇÃO badge permanently, before any click', () => {
    render(<SubscriptionStep onFinish={() => {}} />)

    expect(screen.getByText(/SIMULAÇÃO — nenhuma cobrança real/)).toBeTruthy()
  })

  it('subscribing records the simulated flag and finishes', () => {
    const onFinish = vi.fn()
    render(<SubscriptionStep onFinish={onFinish} />)

    fireEvent.click(screen.getByRole('button', { name: /Assinar \(simulação\)/ }))

    expect($desktopOnboarding.get().postSetup?.subscription.subscribed).toBe(true)
    expect(onFinish).toHaveBeenCalledTimes(1)
  })

  it('gate is off: continuing without subscribing finishes and records nothing', () => {
    const onFinish = vi.fn()
    render(<SubscriptionStep onFinish={onFinish} />)

    fireEvent.click(screen.getByRole('button', { name: 'Continuar sem assinar' }))

    expect($desktopOnboarding.get().postSetup?.subscription.subscribed).toBe(false)
    expect(onFinish).toHaveBeenCalledTimes(1)
  })
})
