# ADR-0017: Deterministic locale contract for product-language parity

- Status: accepted
- Date: 2026-07-13
- Related: issue #192

## Context

Locale coverage already exists as YAML catalogs under `locales/`, and
`agent.i18n` already normalizes user inputs like `en-US` and `pt-BR` onto the
current catalog set. What was missing was a narrow, machine-readable contract
layer that can answer four concrete questions without mutating the catalogs:

- What locale inventory ships, in deterministic order?
- Do the required product locales `en-US` and `pt-BR` resolve to catalogs with
  matching key sets?
- Is a required locale served directly, through alias fallback, or only through
  default-language fallback?
- Does a catalog still carry legacy `Hermes` branding, current `Simplicio Agent`
  branding, both, or neither?

This slice had to stay out of CLI/TUI rendering, rename-guard internals, and
the locale files themselves.

## Decision

`tools/locale_contract.py` defines a transport-agnostic locale contract.

- `build_locale_inventory()` walks `locales/*.yaml` in sorted order and emits a
  deterministic inventory with per-catalog key counts, stable key digests, and
  branding classification.
- Required product locales are declared as `en-US` and `pt-BR`, then resolved
  through the same normalization conventions already used by `agent.i18n`.
- `build_required_locale_parity()` verifies required key parity between the
  resolved baseline (`en-US` -> `en`) and target (`pt-BR` -> `pt`) catalogs.
- `build_locale_receipt()` packages the inventory digest, parity result,
  fallback classification, and branding classification into a machine-readable
  receipt that other doctor/evidence flows can consume later.
- `fixtures/locales/` pins deterministic fixture catalogs plus expected JSON
  outputs so the contract can be regression-tested without coupling tests to the
  full production catalog set.

## Consequences

- Locale inventory is auditable and stable across runs.
- Product-language parity for `en-US` and `pt-BR` is checked at the contract
  layer without editing the locale files.
- Alias fallback versus default fallback becomes explicit instead of implicit.
- Legacy branding drift is visible in receipts instead of being buried inside
  large YAML catalogs.

## Bounded migration follow-up (2026-07-14)

The next #192 slice applied the accepted contract to the shipped source
catalogs. Public catalog values and command examples now use the untranslated
proper name `Simplicio Agent` and canonical command `simplicio-agent` in every
locale. The stable internal key `gateway.update.hermes_cmd_not_found` remains
unchanged, as required by the issue's key-stability rule; a contextual test
allows that identifier while rejecting the legacy term in comments or public
values.

The machine-readable terminology and translator policy lives in
[`docs/product-language-glossary.yaml`](../product-language-glossary.yaml). It
keeps Simplicio Agent distinct from Simplicio Runtime and defines `run`,
`checkpoint`, `receipt`, `capability`, and operational `awareness`.

This follow-up does not complete issue #192. Pseudo-locale layout checks,
priority-locale visual snapshots, RTL coverage, compiled-artifact scanning,
coverage claims, and human language review remain separate acceptance gates.

## Alternatives considered

- Keep parity checks only in `tests/agent/test_i18n.py`: rejected because those
  tests assert behavior but do not emit a reusable machine-readable receipt.
- Add `en-US.yaml` and `pt-BR.yaml`: rejected for this slice because issue #192
  asked for bounded parity infrastructure without changing existing catalogs.
- Scan locale files ad hoc in callers: rejected because it would reimplement the
  same sorting, alias resolution, and branding rules in multiple places.
