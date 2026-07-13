---
name: simplicio-canonical-rename
description: Cross-repo canonical-consumer / CLI rename + deprecation playbook for the Simplicio ecosystem (simplicio-mapper, simplicio-dev-cli, simplicio-loop, etc.). Use when a task rebrands, re-points, or renames a canonical agent/consumer/CLI across repos while keeping the OLD name as a measurable, deprecated alias and preserving upstream fixtures + personal attribution.
trigger:
  - issue/PR says "rebrand", "rename canonical consumer", "make X canonical, deprecate Y", or any cross-repo naming change in simplicio-* repos
  - a repo must stop asserting it is the Agent/Runtime and instead name Simplicio Agent as the canonical consumer/integrator
  - you need to add a new --cli / bootstrap option and retire an old one without breaking JSON/stdout consumers
steps:
  - Read the issue + naming authority it cites (e.g. simplicio-agent#186-#195, simplicio-runtime#NNNN). Build a classification matrix of PRODUCT BRANDING vs UPSTREAM / ATTRIBUTION mentions.
  - Inventory every reference with grep -rIn -i "oldname" repo (exclude node_modules/.git/dist/playwright-report). Split into entry points, docs, generated, and PRESERVE sets.
  - Deprecated-alias pattern: add the NEW canonical option/label; OLD case emits a ONCE-PER-PROCESS STDERR warning (guard e.g. global.__simplicio_deprecation_warned), then delegates; stdout/JSON stays byte-identical; keep OLD keyword in package.json keywords for discoverability.
  - Docs: name canonical consumer; mark old deprecated alias. Regenerate LIVE docs only via the repo sync script. Leave docs-site/versioned_docs/ FROZEN (shipped historical release snapshots).
  - Video i18n + scene: replace old name in consumer orbit / subtitle copy (both locales).
  - Verify via stash-verify.md recipe; run npm run lint + node --test fresh; prove any red is pre-existing by stashing your diff and re-running on the clean tree. End-to-end --cli canonical reaches handoff with no deprecation noise; --cli old emits exactly one STDERR deprecation and delegates.
  - Commit per repo; open PR; leave the UMBRELLA issue OPEN until the correlated repos in the release DAG (mapper -> dev-cli -> loop) apply the same rebrand and the cross-repo release gate is proven.
pitfalls:
  - NEVER delete the old CLI option/keyword — it must remain a MEASURABLE deprecated alias. stdout/stderr separation is the proof it still works.
  - versioned_docs/ are historical releases; rewriting them violates "don't erase published history". Regenerate only docs-site/docs/.
  - Upstream Asolaria ecosystem fixtures and YOOL personal attribution are DATA/ATTRIBUTION, not branding — out of scope, byte-preserve them.
  - Pre-existing CI reds (Node 16 import ... with {} attribute syntax; Python <3.10 int.bit_count()) are ENVIRONMENT issues. Prove via stash; do NOT "fix" them by editing unrelated files in your rebrand PR.
  - A repo keeps its OWN package identity (e.g. simplicio-mapper stays simplicio-mapper — it is the observer/producer of ContextSnapshot). It only re-points the CANONICAL CONSUMER, not its own name.
dod:
  - canonical consumer named in package.json description + keywords; --cli canonical option present in all 3 entry points
  - --cli old emits exactly one STDERR deprecation, delegates, stdout clean (verified by real run)
  - live docs regenerated; git diff shows only docs-site/docs/, NOT versioned_docs/
  - upstream fixtures + attribution byte-identical (git diff excludes them)
  - umbrella issue left open pending correlated-repo release gate
references:
  - references/checklist.md
  - references/stash-verify.md
  - references/invariants.md
---

# Simplicio Canonical Rename

Class-level playbook for cross-repo canonical-consumer / CLI rename + deprecation in the Simplicio ecosystem. Pair with `simplicio-standard-flow` for the base loop.

## When to use
- Rebrand / re-point a canonical agent, consumer, or CLI across repos.
- Keep the OLD name as a MEASURABLE, deprecated alias (not a silent removal).
- Preserve upstream fixtures + personal attribution during the rename.

## Core pattern
1. Classify every mention: PRODUCT BRANDING (rebrand) vs UPSTREAM / ATTRIBUTION (preserve, never touch).
2. Add the canonical option; the old case warns once on STDERR, then delegates — stdout/JSON stay byte-identical (that separation is the compatibility proof).
3. Regenerate LIVE docs only; leave `versioned_docs/` frozen (don't erase published history).
4. Verify via stash (see `references/stash-verify.md`); run the real end-to-end dispatch check.
5. Leave the umbrella issue OPEN until the correlated repos in the release DAG (mapper → dev-cli → loop) apply the same change and the cross-repo release gate is proven.

See the `references/` files for the exact file-touch matrix, the stash-verify recipe, and the ecosystem invariants to preserve.
