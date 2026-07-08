// Pure logic for the post-provider setup sequence (doctor -> simulated Google
// sign-in -> simulated subscription). Kept free of store/React imports so it
// can be unit-tested directly (post-setup.test.ts) even where the UI deps
// aren't installable — this is the logic the command palette's
// "Setup Simplicio" entry triggers via startManualPostSetup() in
// src/store/onboarding.ts.

export const POST_SETUP_SEQUENCE = ['post_doctor', 'post_google', 'post_subscription'] as const

export type PostSetupStatus = (typeof POST_SETUP_SEQUENCE)[number]

/** The exact store patch that re-enters the setup sequence from a configured
 *  app: manual-mode overlay (close affordance, no first-run gate), no reason
 *  banner, and the flow parked on the FIRST post-setup step — the provider
 *  picker is skipped entirely since a provider already exists. */
export interface ManualPostSetupPatch {
  flow: { status: PostSetupStatus }
  localEndpoint: false
  manual: true
  reason: null
  requested: true
}

export function manualPostSetupPatch(): ManualPostSetupPatch {
  return {
    manual: true,
    requested: true,
    localEndpoint: false,
    reason: null,
    flow: { status: POST_SETUP_SEQUENCE[0] }
  }
}

/** Next step in the sequence, or null when `current` is the last step (the
 *  caller finishes onboarding instead of advancing). */
export function nextPostSetupStatus(current: PostSetupStatus): null | PostSetupStatus {
  const index = POST_SETUP_SEQUENCE.indexOf(current)

  return index >= 0 && index + 1 < POST_SETUP_SEQUENCE.length ? POST_SETUP_SEQUENCE[index + 1] : null
}
