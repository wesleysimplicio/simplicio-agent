# ADR-0018: Public docs audit for branding, commands, and unsupported claims

- Status: accepted
- Date: 2026-07-13
- Related: issue #189

## Context

Issue #189 needs bounded, reviewable evidence that public docs/examples can be
audited for rename leakage without rewriting the docs corpus in the same pass.
The evidence slice must stay deterministic, stay focused on public-facing text,
and distinguish acceptable legacy references from actual regressions.

The concrete risks in this slice are narrow:

- legacy Hermes product naming leaking into public docs/examples
- legacy `hermes` / `hermes-agent` command examples surviving after the
  canonical command switched to `simplicio-agent`
- unsupported capability claims stated as facts in public docs
- migration and credit contexts being incorrectly flagged as regressions

## Decision

Add `tools/public_docs_audit.py` as a bounded line-oriented scanner with a
machine-readable report.

The audit is intentionally explicit, not heuristic-heavy:

- legacy command findings come from a fixed `hermes` / `hermes-agent` command
  matcher
- legacy brand findings come from a fixed Hermes-name matcher
- unsupported capability findings come from a curated denylist of exact claim
  patterns
- migration and credit exceptions use path-aware reviewed allowlist entries,
  never a global suppression
- an allowlisted line suppresses only its legacy branding/command finding; the
  unsupported-claim rules still run on that same line

The report schema is `simplicio.public-docs-audit/v1` and includes:

- audited file count
- finding count
- allowlisted line count
- aggregate counts by rule and severity
- per-finding evidence: path, line, column, rule, message, matched text,
  evidence line, and suggested replacement

The tool is evidence-only in this slice. It does not rewrite docs, mutate an
allowlist on disk, or claim repo-wide cleanliness.

## Consequences

- Public-docs review gets a deterministic receipt for the bounded issue #189
  surface without editing unrelated docs.
- Migration guidance and upstream credit remain possible without teaching the
  scanner to ignore Hermes references globally.
- Unsupported claims are only flagged when they match a reviewed explicit
  pattern; unmodeled claims still require human review.
- The current evidence remains intentionally partial: this slice proves the
  audit contract and test corpus, not the full repo's public-docs state.

## Alternatives considered

- **Bulk rewrite public docs in the same PR:** rejected because issue #189 asked
  for an evidence slice, not a repo-wide content migration.
- **Reuse the rename guard baseline/allowlist files directly:** rejected because
  this slice needs line-level public-doc semantics, unsupported-claim rules,
  and canonical-command evidence rather than repo-wide brand inventory counts.
- **Flag every Hermes mention unconditionally:** rejected because reviewed
  migration and credit references are legitimate public-doc content.
