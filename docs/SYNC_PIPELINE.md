# Ecosystem Sync Pipeline

Repeatable tooling to keep Simplicio in sync with its upstream lineage without
ever reverting newer code. Encoded in `scripts/sync/ecosystem-sync.sh` and the
`ecosystem-sync` GitHub workflow.

## The pipeline

```
Hermes Agent                         Hermes Turbo Agent                Simplicio (this repo)
github.com/NousResearch/hermes-agent   $TURBO_REPO                     github.com/wesleysimplicio/simplicio-agent
        │                                    │                                  │
        │  (1) turbo-absorb-hermes           │                                  │
        └──────────── fetch + merge ────────▶│                                  │
                                             │  adds its performance layer      │
                                             │                                  │
                                             │  (2) simplicio-pull-perf         │
                                             └──── copy PERF DELTA (additive) ─▶│
                                                                                │  + ecosystem updates
                                                                                │  + Asolaria/JesseBrown1980
```

1. **Hermes Agent** — the canonical upstream (`NousResearch/hermes-agent`).
2. **Hermes Turbo Agent** — absorbs the latest Hermes, then layers on its
   performance work.
3. **Simplicio** (this repo) — pulls Turbo's **perf delta** additively, plus
   updates from the rest of the `Projetos/ai` ecosystem and the
   Asolaria / JesseBrown1980 line.

## Critical ordering constraint (and WHY)

**Simplicio is currently NEWER than Turbo.** Simplicio is at **v0.18.0** on a
recent Hermes baseline; Turbo sits on an older Hermes base. A blind "copy
everything from Turbo into Simplicio" would **REVERT** newer Simplicio code.

So the pipeline must run in this order, every time:

1. **Turbo absorbs the latest Hermes FIRST** (`turbo-absorb-hermes`). This
   brings Turbo's base up to (or past) the Hermes revision Simplicio already
   sits on, so the perf delta is computed against a current base — not a stale
   one.
2. **Only THEN Simplicio pulls from Turbo** (`simplicio-pull-perf`) — and even
   then it pulls the **perf delta ADDITIVELY**, file by file, **skipping any
   file that is newer in Simplicio**. It never wholesale-overwrites newer files.

### Guards baked into the tooling

- **Ordering guard.** `simplicio-pull-perf` calls `_ordering_guard` before
  copying: it fetches upstream in the Turbo repo and checks whether Turbo is
  behind `upstream/main`. If Turbo is behind:
  - in `--dry-run`: it warns and prints the human-review note;
  - in `--apply`: it **aborts** with a non-zero exit and tells you to run
    `turbo-absorb-simplicio-agent --apply` first.
  - If upstream can't be reached (offline CI), it degrades to a warning rather
    than a false pass.
- **Additive, newer-file-safe copy.** For every file in the perf set, a Turbo
  file is copied only when the Simplicio target is **missing** OR the Turbo file
  is **strictly newer** (git commit time when tracked, else mtime). Files that
  differ but where Simplicio is newer/equal are logged as
  `SKIPPED-because-newer-in-Simplicio` and left untouched.
- **Never silently overwrite.** Every action is logged as
  copied / would-copy / skipped-newer / skipped-identical / needs-human-review.
- **Destructive steps behind `--apply`.** Default is `--dry-run`. No file is
  written, no merge is staged, no fast-forward is pulled without `--apply`.

## The additive perf module set (canonical copy list)

This is the exact set already ported into Simplicio (documented in
`CHANGELOG.md` under `[0.18.0]`). `simplicio-pull-perf` uses it as the copy list:

| Path | What it is |
|---|---|
| `agent/serde/` | orjson/msgspec fast JSON with stdlib fallback |
| `agent/tokens/` | tiktoken fast token estimator with `len // 4` fallback |
| `agent/tracing/` | OTel-compatible lightweight span emitter |
| `agent/net/` | HTTP/2 keep-alive connection pool over httpx |
| `agent/async_dag/` | dependency-aware parallel tool batch executor |
| `agent/router/` | deterministic no-LLM + cost-aware multi-tier router |
| `agent/telemetry/` | stage timing, token-savings ledger, receipts |
| `agent/providers/` | provider fallback chain w/ jittered backoff |
| `agent/project_mapper/` | stdlib manifest-based stack fingerprint |
| `agent/_fastjson.py` | fast JSON shim |
| `agent/_hermes_fast.py` | pure-Python fallback for the Rust hot path |
| `agent/uvloop_utils.py` | uvloop event-loop policy installer |
| `agent/simplicio_prompt.py` | env-gated system-prompt prep |
| `rust_ext/` | optional `hermes_fast` PyO3 extension |
| `plugins/token_saver/` | terminal/tool output compactor |
| `pyproject.toml` (`fast`/`perf` extras + `maturin`) | perf install extras |

> Note on `pyproject.toml`: the extras/`maturin` change is part of the ported
> set but is **not** wholesale-copied by `simplicio-pull-perf` (it would clobber
> other Simplicio project metadata). Treat it as a manual, reviewed merge — the
> `[0.18.0]` changelog entry records the exact keys.

**Intentionally excluded** (per `[0.18.0]`): the fork's rebrand (Tota → Hermes
Turbo), the fork's upstream-sync tooling, benchmark/PDF scripts, and
`agent/auto_mapper.py` / `agent/metrics.py`.

## Subcommands

```
scripts/sync/ecosystem-sync.sh <subcommand> [--dry-run|--apply] [options]
```

| Subcommand | Does |
|---|---|
| `turbo-absorb-hermes` | In the Turbo repo: ensure the `upstream` remote, fetch `NousResearch/hermes-agent`, print the ahead/behind + diff summary, and **stop for human review**. `--apply` stages a **non-destructive** (`--no-commit`) merge; a human reviews, commits, pushes. |
| `simplicio-pull-perf` | Copy the additive perf set from Turbo into Simplicio, skipping any file newer in Simplicio, then run `validate`. Enforces the ordering guard. |
| `ecosystem-update` | Fetch/report (and with `--apply`, fast-forward) other `Projetos/ai` repos. Parameterizable via `ECOSYSTEM_REPOS` or positional paths. |
| `asolaria-absorb` | Read `docs/ASOLARIA_ABSORPTION_PLAN.md`'s "Status tracking" checkboxes and list pending items with their license class (`mit-safe` vs `reimplement-only`). `--apply --complete <id>` checks off one item after a human has done the (re)implementation work; `reimplement-only` items additionally require `--confirm-reimplemented`. Never copies source files itself — see below. |
| `validate` | The gate: python import smoke of the perf modules + targeted `pytest` on the ported perf suites. Exits non-zero on regression. |

### Flags & environment

- `--dry-run` (default): report only, never write or merge.
- `--apply`: enact destructive steps.
- `SIMPLICIO_REPO` — this repo root (default: git toplevel of the script).
- `TURBO_REPO` — hermes-turbo-agent checkout (default: sibling `hermes-turbo-agent`).
- `HERMES_UPSTREAM` — upstream URL (default: `https://github.com/NousResearch/hermes-agent.git`).
- `HERMES_UPSTREAM_REMOTE` / `HERMES_UPSTREAM_BRANCH` — default `upstream` / `main`.
- `ECOSYSTEM_REPOS` — space/comma list of repo paths for `ecosystem-update`.
- `PYTHON` — interpreter for the validation gate (default `python3`).

## Running it locally

```bash
# 0. Full dry-run of the perf pull + validation gate (safe, no writes):
scripts/sync/ecosystem-sync.sh simplicio-pull-perf --dry-run

# 1. Bring Turbo up to date with Hermes FIRST (staged merge, human commits):
TURBO_REPO=/path/to/hermes-turbo-agent \
  scripts/sync/ecosystem-sync.sh turbo-absorb-simplicio-agent --apply

# 2. THEN pull the additive perf delta into Simplicio (skips newer files):
TURBO_REPO=/path/to/hermes-turbo-agent \
  scripts/sync/ecosystem-sync.sh simplicio-pull-perf --apply

# 3. Re-run the gate on its own anytime:
scripts/sync/ecosystem-sync.sh validate

# 4. Ecosystem + Asolaria (report only):
scripts/sync/ecosystem-sync.sh ecosystem-update --dry-run
scripts/sync/ecosystem-sync.sh asolaria-absorb
```

## Running it via CI

The `ecosystem-sync` workflow (`.github/workflows/ecosystem-sync.yml`):

- `workflow_dispatch` with a `mode` input (`dry-run` default, or `apply`).
- Weekly schedule (Mondays 06:00 UTC), always dry-run.
- Runs `simplicio-pull-perf` then `validate`, posting both logs to the run
  summary.
- **Dry-run by default and never auto-pushes synced content.** Turbo is not
  checked out in CI, so the pull degrades gracefully and the gate is what
  actually protects `main`. Enacting a real sync is a deliberate local `--apply`
  by a human, followed by a normal PR.

## How Asolaria plugs in

`asolaria-absorb` reads `docs/ASOLARIA_ABSORPTION_PLAN.md`'s "Status tracking"
section and lists every unchecked `- [ ] N.` item as pending, cross-referenced
against a canonical `ASOLARIA_ITEMS` table in the script (id, priority,
license class, title — kept in sync with the plan by hand).

Unlike `simplicio-pull-perf`, this subcommand does **not** copy files from a
single upstream checkout: Asolaria is ~9 disparate external repos, most with
**no license file** (all-rights-reserved by default) or an unresolved
`NOASSERTION`, and the plan itself says to reimplement those from the public
README/spec rather than vendor the code. Auto-copying unreviewed,
all-rights-reserved source would be the opposite of "additive and safe."

So `--apply` has narrower, safer teeth: `--apply --complete <id>` flips one
item's checkbox after a human confirms the (re)implementation actually
landed elsewhere in the codebase. Items classed `reimplement-only` refuse to
complete without an explicit `--confirm-reimplemented`; items classed
`mit-safe` (currently `ai-memory` and `scala-critical-path-planner`, both
MIT) can be marked complete once vendored/ported, but this script still never
performs that vendoring itself — only the checkbox update, followed by the
same `validate` gate `simplicio-pull-perf` runs.
