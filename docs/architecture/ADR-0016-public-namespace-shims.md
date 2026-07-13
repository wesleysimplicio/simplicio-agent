# ADR-0016: Public namespace shims for `simplicio_agent`

- Status: accepted
- Date: 2026-07-13
- Related: issue #190

## Context

The shipped product name is Simplicio Agent, but the Python implementation
still lives under Hermes-rooted modules such as `run_agent.py`, `cli.py`, and
`hermes_cli/`. External callers need a stable product-facing import path
without renaming internals, rewriting registries, or creating wrapper classes
that break identity-sensitive code.

We also need a bounded compatibility bridge for legacy imports during the
rename transition. That bridge must guide callers toward the canonical public
names while preserving the exact runtime classes and module singletons already
used by the rest of the process.

## Decision

Add a new top-level package `simplicio_agent` as a thin facade only:

- `simplicio_agent.Agent` lazily resolves to `run_agent.AIAgent`.
- `simplicio_agent.CLI` lazily resolves to `cli.HermesCLI`.
- `simplicio_agent.main` lazily resolves to `hermes_cli.main.main`.
- `simplicio_agent.__version__` and `__release_date__` forward from
  `hermes_cli`.

The facade does not subclass, wrap, or re-register anything. It imports the
existing modules on demand and returns the existing objects verbatim, so
identity stays stable (`simplicio_agent.Agent is run_agent.AIAgent`) and no
second tool or capability registry can appear.

Add `simplicio_agent.compat` as a deprecation-only shim:

- `simplicio_agent.compat.AIAgent` returns `simplicio_agent.Agent`
- `simplicio_agent.compat.HermesCLI` returns `simplicio_agent.CLI`
- each access emits `DeprecationWarning`

Ship `simplicio_agent/py.typed` and package it in the wheel so the public
namespace is PEP 561 typed.

## Consequences

- Product-facing Python imports can converge on `simplicio_agent` without any
  internal rename.
- Existing Hermes module ownership and singleton state stay intact.
- Legacy callers get a narrow, explicit migration path instead of silent drift.
- Installed-package tests cover the real wheel artifact, not only source-tree
  imports.

## Alternatives considered

- **Rename internal modules to `simplicio_*`:** rejected because the project
  explicitly preserves Hermes-rooted internals as a cross-repo contract.
- **Wrapper subclasses or proxy objects:** rejected because class identity,
  `isinstance` checks, and module-level singleton state would drift.
- **Re-export from multiple new packages:** rejected because it widens the
  public surface and increases the risk of duplicate import graphs.
