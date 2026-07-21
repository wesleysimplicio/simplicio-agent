# Definition of Done — simplicio-agent

Cross-repo DoD rollout, hub: [simplicio-loop#579](https://github.com/wesleysimplicio/simplicio-loop/issues/579).
Local proposal issue: [#488](https://github.com/wesleysimplicio/simplicio-agent/issues/488).

## Scope check first (do not skip)

Issue #488 proposed a thin-wrapper framing for this repo ("a maior parte da
lógica de correção vive no runtime"). That framing does **not** hold — verify
before assuming otherwise on future work here:

- `agent/` alone is ~735k lines across ~300 modules (memory, providers,
  tool execution, skills, gateways, protocol codecs, learning graph,
  compression, telemetry — not runtime glue).
- The repo is a public fork of `NousResearch/hermes-agent` (see `README.md`
  "Hermes → Simplicio Agent"): the Hermes agent core is the majority of the
  product, evolved in place, not called out to.
- `simplicio-runtime` integration is one dependency among many, isolated to
  `tools/runtime_manager.py` + `tools/runtime_handshake.py` +
  `agent/runtime_bridge.py` (pin/handshake/managed-install lifecycle) — a
  small, well-bounded slice of the tree, not "most of it."
- The repo already runs its own mature test discipline: 2296 test files,
  `.coveragerc` / `.coveragerc.core` both gate `fail_under = 85`, CI
  (`.github/workflows/tests.yml`) shards the suite across 8 parallel slices,
  plus dedicated lint/docker/lockfile/OSV/supply-chain workflows.

**Conclusion used below:** this repo needs a full DoD for its own logic (same
weight as any other primary codebase in the ecosystem), not a pointer-only
stub. The one place that genuinely mirrors "wrapper" territory is the runtime
handshake/lifecycle slice, called out explicitly in Layer 2.

## The 4 layers

### Layer 1 — Unit

- `pytest tests/ -v` (or `scripts/run_tests.sh`, same invocation CI uses)
  green for the touched module(s).
- New/changed logic gets a same-PR unit test; no "will add tests later."
- Coverage: `.coveragerc` (`tests/ci/`) and `.coveragerc.core`
  (`agent/`, `gateway/`, `tools/`, `hermes_cli/`, `cli.py`, `run_agent.py`)
  both enforce `fail_under = 85`. The aggregated CI gate runs the full Python
  suite with `.coveragerc.core` and blocks below that 85% threshold via the
  reusable `coverage` workflow. Do not lower either threshold to land a PR.

### Layer 2 — Integration

- Cross-module wiring gets a test under `tests/integration/` (existing
  examples: `test_golden_path.py`, `test_checkpoint_resumption.py`,
  `test_batch_runner.py`) exercising the real call path between the modules
  involved, not each module re-tested in isolation.
- **Runtime integration specifically** (`tools/runtime_manager.py`,
  `tools/runtime_handshake.py`, `agent/runtime_bridge.py`): today every test
  here (`tests/tools/test_runtime_manager.py`,
  `tests/tools/test_runtime_handshake.py`,
  `tests/tools/test_runtime_lifecycle.py`) is synthetic/mocked — no test
  shells out to a real, compiled `simplicio` binary. That is a known,
  acceptable gap for routine changes to this slice (the binary is an external
  managed dependency, not built by this repo), but:
  - A change to the handshake/version-satisfies/managed-install contract
    itself (`RuntimeHandshake`, `CompatibilityMatrix`,
    `version_satisfies`, `probe_kernel_version`) MUST add or update at least
    one test that runs against a real `simplicio` binary when one is
    reachable on `PATH` (`shutil.which("simplicio")`), skipping cleanly
    (never mocking-as-if-real) when it is not. This is the concrete
    "integração com o runtime real, não mockado" instance issue #488 asked
    for — implement it at the point where this repo actually talks to the
    binary, not as a blanket rule over unrelated code.
  - Do not duplicate `simplicio-runtime`'s own correctness testing here
    (its command surface, its internal logic) — that discipline lives in
    the runtime repo's own DoD. This repo only owns the consumer side of the
    contract: can it detect/pin/install/talk to a compatible binary.

### Layer 3 — System / E2E

- User-observable flows get an end-to-end test through the real entry point:
  `tests/e2e/` (CLI/platform commands), `tests/hermes_cli/` (CLI dispatch),
  or a `pytest -m integration`-marked flow like
  `tests/test_wheel_locales_e2e.py` for packaging-shaped changes.
- Assert on the **observable end state** (file content, response payload,
  emitted event/receipt), not on the tool's own self-reported
  status/exit-code alone — this is the exact failure mode from the hub issue
  (a tool reporting `"status": "ok"` while silently producing a wrong
  result).

### Layer 4 — Deep-correctness gate (new, per hub #579)

Applies when a change touches parsing/transformation of structured data where
two code paths can process the same structure with different assumptions
(this repo has many candidates: `agent/toon_codec.py`, `agent/protocol.py` /
`protocol_v1.py`, `agent/message_content.py`, `agent/task_envelope.py`,
`agent/learning_graph.py`, `agent/context_compressor.py`,
`agent/tool_call_json.py`).

- **Property-based testing.** Target tool: `hypothesis` (not currently a
  dependency of this repo — adding it requires the standing "ask before new
  dependency" step in `AGENTS.md`/`CONTRIBUTING.md` before it lands, it is
  not pre-approved by this document). Until then, hand-written example
  tables must cover the combination space the change actually touches, not
  just one representative shape per branch.
- **Real-shaped fixtures.** At least one test case for parsing/transform
  changes uses realistic input (an actual multi-turn transcript, a real
  TOON/JSON payload, real skill frontmatter) — not a 2-line synthetic
  snippet. The mapper bug that motivated the hub issue only showed up on
  idiomatic PEP8-formatted source, never on minimal fixtures.
- **Invariant review question in the PR** (see template below): if this PR
  adds a function that partitions/groups a collection that another function
  also processes, do both use the same granularity/key? Answer it explicitly
  even when the answer is "N/A — no second consumer of this structure."
- **Observable-result assertion**, restated from Layer 3: a test that only
  checks `result.status == "ok"` / no exception raised does not satisfy this
  layer for parsing/transform code — assert on the actual decoded/produced
  value.

## PR template

`.github/PULL_REQUEST_TEMPLATE.md` already existed with a code checklist
(tests run, tested on platform, etc.). Added for this DoD:

- An **invariant question** under "How to Test": the exact partition/grouping
  question from Layer 4.
- An **observable-evidence checklist item**: real command/output pasted, or
  the specific test name run — not just "tests pass."

## What NOT to do here

- Do not build a mutation-testing or fuzzing harness generically across
  `agent/` speculatively — scope Layer 4 to the change's own touched
  parsing/transform surface, per PR, as the hub issue specifies.
- Do not re-implement `simplicio-runtime`'s command-surface correctness
  tests in this repo "for completeness" — that duplicates ownership and
  drifts the moment either side changes independently.
- Do not add `hypothesis` (or any new test dependency) as a side effect of
  adopting this document — it needs its own explicit user confirmation.
