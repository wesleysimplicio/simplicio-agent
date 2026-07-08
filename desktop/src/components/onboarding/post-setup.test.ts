import { describe, expect, it } from 'vitest'

import { manualPostSetupPatch, nextPostSetupStatus, POST_SETUP_SEQUENCE } from './post-setup'

describe('manualPostSetupPatch (command palette "Setup Simplicio" -> manual post-setup mode)', () => {
  it('opens the overlay in manual mode parked on the first post-setup step', () => {
    const patch = manualPostSetupPatch()

    // manual=true bypasses the configured===true gate in
    // DesktopOnboardingOverlay, so the overlay opens even when a provider is
    // already configured (the E2E-discovered unreachability case).
    expect(patch.manual).toBe(true)
    expect(patch.requested).toBe(true)
    // Parked directly on the doctor step: showPicker (idle|success) is false,
    // so FlowPanel renders DoctorStep instead of the provider picker.
    expect(patch.flow).toEqual({ status: 'post_doctor' })
    // No stale reason banner and no local-endpoint form takeover.
    expect(patch.reason).toBeNull()
    expect(patch.localEndpoint).toBe(false)
  })

  it('starts at the first entry of the canonical sequence', () => {
    expect(manualPostSetupPatch().flow.status).toBe(POST_SETUP_SEQUENCE[0])
  })
})

describe('POST_SETUP_SEQUENCE', () => {
  it('runs doctor -> google -> subscription, in that order', () => {
    expect(POST_SETUP_SEQUENCE).toEqual(['post_doctor', 'post_google', 'post_subscription'])
  })
})

describe('nextPostSetupStatus', () => {
  it('advances doctor -> google -> subscription', () => {
    expect(nextPostSetupStatus('post_doctor')).toBe('post_google')
    expect(nextPostSetupStatus('post_google')).toBe('post_subscription')
  })

  it('returns null after the last step (caller finishes onboarding)', () => {
    expect(nextPostSetupStatus('post_subscription')).toBeNull()
  })
})
