import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  $desktopOnboarding,
  advanceFromDoctor,
  advanceFromGoogle,
  DEFAULT_POST_SETUP_STATE,
  type DesktopOnboardingState,
  finishPostSetup,
  setGoogleSignedIn,
  setSubscribed,
  startManualPostSetup
} from './onboarding'

// Store-level coverage for the command palette's "Setup Simplicio" entry
// (src/app/command-palette/index.tsx, item id 'setup'): its run() calls
// startManualPostSetup(), which must open the manual onboarding overlay
// parked on the post-setup sequence even when a provider is already
// configured — the E2E-discovered case where first-run onboarding never
// shows and the doctor/google/subscription steps were unreachable.
// The pure patch shape itself is covered in
// src/components/onboarding/post-setup.test.ts.

function baseState(overrides: Partial<DesktopOnboardingState> = {}): DesktopOnboardingState {
  return {
    configured: false,
    flow: { status: 'idle' },
    mode: 'oauth',
    providers: null,
    reason: null,
    requested: false,
    firstRunSkipped: false,
    manual: false,
    localEndpoint: false,
    postSetup: DEFAULT_POST_SETUP_STATE,
    ...overrides
  }
}

beforeEach(() => {
  window.localStorage.clear()
  $desktopOnboarding.set(baseState())
})

afterEach(() => {
  window.localStorage.clear()
  $desktopOnboarding.set(baseState())
  vi.restoreAllMocks()
})

describe('startManualPostSetup (palette "Setup Simplicio")', () => {
  it('opens manual mode parked on post_doctor even when already configured', () => {
    // Provider already configured — the state that makes the first-run
    // overlay never open (DesktopOnboardingOverlay returns null unless
    // manual===true).
    $desktopOnboarding.set(baseState({ configured: true }))

    startManualPostSetup()

    const state = $desktopOnboarding.get()
    expect(state.manual).toBe(true)
    expect(state.requested).toBe(true)
    expect(state.flow).toEqual({ status: 'post_doctor' })
    // configured stays true — this never downgrades a working app.
    expect(state.configured).toBe(true)
    // No stale reason banner, no local-endpoint form takeover.
    expect(state.reason).toBeNull()
    expect(state.localEndpoint).toBe(false)
  })

  it('walks doctor -> google -> subscription and closes normally via finishPostSetup', () => {
    $desktopOnboarding.set(baseState({ configured: true }))
    startManualPostSetup()

    advanceFromDoctor()
    expect($desktopOnboarding.get().flow).toEqual({ status: 'post_google' })

    setGoogleSignedIn('voce@exemplo.com')
    expect($desktopOnboarding.get().postSetup?.google).toEqual({ signedIn: true, email: 'voce@exemplo.com' })

    advanceFromGoogle()
    expect($desktopOnboarding.get().flow).toEqual({ status: 'post_subscription' })

    setSubscribed(true)
    expect($desktopOnboarding.get().postSetup?.subscription.subscribed).toBe(true)

    const onCompleted = vi.fn()
    finishPostSetup({ requestGateway: async () => undefined as never, onCompleted })

    const state = $desktopOnboarding.get()
    // completeDesktopOnboarding ran: overlay closes (manual cleared),
    // configured persists, flow resets, simulated postSetup state resets.
    expect(onCompleted).toHaveBeenCalledTimes(1)
    expect(state.manual).toBe(false)
    expect(state.requested).toBe(false)
    expect(state.configured).toBe(true)
    expect(state.flow).toEqual({ status: 'idle' })
    expect(state.postSetup).toEqual(DEFAULT_POST_SETUP_STATE)
  })

  it('step guards no-op outside their own status', () => {
    $desktopOnboarding.set(baseState({ configured: true, flow: { status: 'idle' } }))

    advanceFromDoctor()
    advanceFromGoogle()
    finishPostSetup({ requestGateway: async () => undefined as never })

    const state = $desktopOnboarding.get()
    expect(state.flow).toEqual({ status: 'idle' })
    // finishPostSetup outside post_subscription must NOT complete onboarding.
    expect(state.configured).toBe(true)
    expect(state.manual).toBe(false)
  })
})
