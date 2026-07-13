# ADR-0019: Bounded CLI/TUI Surface Identity Contract

- Status: Accepted
- Date: 2026-07-13
- Issue: #188

## Context

`simplicio-agent` is the canonical public command. The repo still carries
intentional compatibility aliases (`hermes`, `hermes-agent`, `hermes-acp`) and
legacy internal naming (`HERMES_*`, module paths, package names). That is not a
full-rename program.

Issue #188 needs a bounded, testable contract for the public CLI/TUI surface
without editing the live CLI/TUI implementation, facade wiring, or alias
registries. The proof target is policy conformance, not runtime exhaustiveness.

The existing repo conventions that this ADR freezes are:

- `hermes_constants.py` exports `CANONICAL_CLI_NAME = "simplicio-agent"`.
- `hermes_cli/main.py` prints a once-per-day deprecated-alias nudge instead of
  removing alias support.
- `ui-tui` and `tui_gateway` expose branding through `gateway.ready` and
  `skin.changed`, rather than via alternate CLI names.

## Decision

Add a bounded contract module at `tools/cli_surface_contract.py` with fixture
coverage in `fixtures/cli-identity/` and focused tests in
`tests/tools/test_cli_surface_contract.py`.

The contract is deterministic and static:

1. Canonical public command names must be `simplicio-agent`.
2. Legacy aliases are migration-only compatibility shims, not equal public
   brands and not candidates for a fake full rename.
3. Public messages are classified deterministically as one of:
   `canonical_hint`, `migration_notice`, `branding_event`,
   `neutral_public_text`.
4. Receipts must be safe to persist: no raw argv, no secret-bearing keys, no
   token-like values.

## Consequences

- This gives issue #188 a bounded proof surface that can be enforced with
  deterministic fixtures and tests.
- This does not prove that every live CLI/TUI path already emits compliant
  text. It proves the public-surface contract expected of those paths.
- Future live-surface audits can consume the same manifest/checker without
  expanding the current ownership boundary.
