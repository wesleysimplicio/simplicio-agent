# Unified Governance — Specification

> **Issue:** #54 — [P3] Governanca Unificada
> **Spec version:** 1.0 (2026-07-03)

## Objective

Establish a unified contribution and governance model for the Simplicio
Agent project — a single set of rules for how code gets in, how decisions
are made, and how quality is enforced.

## Scope

Governance covers:

1. **Contribution workflow** — PR process, review rubrics, Definition of Done
2. **Decision records** — ADR process for architecture decisions
3. **Quality gates** — what must pass before a PR merges
4. **Community model** — maintainers, contributors, code of conduct
5. **Release process** — versioning, changelog, release notes

## Deliverables

### Phase 1 — Foundation (P3a)

- [ ] **`CONTRIBUTING.md`** — unified contribution guide (currently Hermes-era,
  needs Simplicio-specific updates for kernel binding, telemetry, etc.)
- [ ] **Definition of Done (DoD) checklist** — standard PR template with
  mandatory checkboxes:
  - Tests pass (new + existing)
  - Ruff lint clean
  - ADR if architecture change
  - Token savings report if perf-impacting (see below)
  - Conventional commits format
  - Cross-platform tested or noted

### Phase 2 — Process (P3b)

- [ ] **Code review rubric** — formal criteria for approving PRs:
  - Correctness (tests cover the change)
  - Cache-safety (no mid-conversation format changes)
  - Honest degradation (no fabricated success)
  - Narrow waist (new core tools require strong justification)
- [ ] **ADR process documented** — when to write one, how to format, where
  to store (`docs/architecture/ADR-NNNN-name.md`)

### Phase 3 — Automation (P3c)

- [ ] **`scripts/check.py`** — pre-merge validation runner:
  - Ruff lint
  - Pytest (scoped to changed files)
  - Link checker for docs
  - DoD compliance report
- [ ] **GitHub Actions** — CI that enforces the DoD checklist:
  - Label check: every PR needs a type label (feat/fix/docs/chore)
  - Size check: flag oversized PRs for human review
  - DoD gate: blocks merge if checklist incomplete

## Token savings report mandate

Every PR that could affect performance (new tool, changed compression,
different serialization, new LLM call) MUST include a token savings report
in the PR body:

```
## Token impact
- Context saved per turn: ~X tokens (methodology)
- Wall-clock change: +Y% / -Z% (benchmark link)
- Cache layout changed? Yes/No (if Yes, explain why session-start-pinned)
```

This is the **canonical policy** — no perf-impacting PR merges without numbers.

## Release process

- **Versioning**: SemVer (major.minor.patch)
- **Release cadence**: no fixed schedule; release when DoD gates are green
  and a meaningful feature set is ready
- **Changelog**: `CHANGELOG.md` updated per release, categorized by
  conventional commit type
- **Release checklist**:
  1. All issues in the milestone closed
  2. DoD checklist complete
  3. Token savings report updated for the release
  4. Tag + GitHub Release + publish artifacts (PyPI, Homebrew, Docker)

## References

- Issue #54 (this spec)
- `CONTRIBUTING.md` (current Hermes-era version)
- `AGENTS.md` (development guide)
- `docs/architecture/` (existing ADRs)
- `docs/roadmap/SIMPLICIO-ROADMAP.md` (strategic context)
