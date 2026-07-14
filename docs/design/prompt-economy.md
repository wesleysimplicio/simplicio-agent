# Prompt economy

The prompt-economy layer provides a bounded progressive-disclosure slice for
the system prompt. The compact index keeps short handles and summaries in the
stable prompt tier; the full text is resolved only when a caller explicitly
expands a handle. The `agent.prompt_economy` setting defaults to `true`, so
new installations receive the measured compact path; set it to `false` to
retain eager, full-text guidance.

Safety guidance remains eager. Only the conservative handles listed by
`agent.prompt_economy.COMPACTABLE_HANDLES` may be summarized; identity,
behavior, tool-use, and model-execution guidance is never compacted. Tool
pinning is an ordering operation over the complete input bundle: every tool
and schema remains available, and a fixed `(tools, task)` pair produces the
same order.

## Deterministic expansion receipts

`expand_instruction(handle)` remains the compatibility string API. Consumers
that need local evidence can call
`expand_instruction_with_receipt(handle, ...)`, which returns `(text,
receipt)`. An `ExpansionReceipt` contains:

- UTF-8 content hash and character/byte sizes;
- the selected, already-pinned tool bundle (when supplied via `tools` + `task`
  or `selected_bundle`);
- whether a fallback was used and a stable fallback reason; and
- `cache_stable` / `prefix_invalidated` fields describing the caller's
  insertion strategy.

Receipts intentionally contain no timestamp or provider-token claim. The
normal expansion is append-only and reports `cache_stable=True` and
`prefix_invalidated=False`; a caller rebuilding the stable system prompt must
set `prefix_invalidated=True`. If a known body cannot be imported, the caller
fallback is used when supplied, otherwise the catalog summary is returned. An
unknown handle still raises `KeyError` unless the caller supplies an explicit
fallback.

These local sizes and hashes are evidence about the assembled payload only.
Provider-side token savings require a provider usage/cache receipt and must
not be inferred from this API.

## Bounded-slice audit (origin/main, 2026-07-14)

The focused catalog measurement is deterministic: the compact index is 1,705
characters versus 15,505 characters for the resolvable full bodies. For the
five conservative compactable sections, the default compact block is 750
characters versus 7,784 characters of full guidance (90.4% fewer characters,
using the local four-characters-per-rough-token estimate). The block has an
800-character cap; callers can use `compact_block_receipt(...)` to capture
the active handles, exact character/UTF-8 byte counts, rough token counts,
content hash, and local savings without changing the cached prefix.

`pin_capability_bundle(...)` remains an ordering-only helper. It preserves
every input schema, including OpenAI `{"type": "function", "function": ...}`
wrappers, and must be computed once at session freeze if used. It is not a
schema reducer and is not currently wired into request construction;
provider-side tool-schema tax reduction is therefore **UNVERIFIED** by this
slice and requires a separate integration change plus provider usage/cache
evidence. No claim of billed-token savings follows from the local receipts.

## Native #317/#318 bounded slice

`agent.token_governor.TokenGovernor` adds a deterministic L0–L3 decision
boundary around this existing economy layer. L0 cache/receipt hits and L1
deterministic routes have zero remote input/output budget; L2 stays local when
entropy is within the guided threshold; only L3 receives a frontier budget.
Every decision returns a content-free SHA-256 intent fingerprint, explicit
input/output/schema budgets, and an escalation/fallback reason. The governor
does not call a provider or emit the intent text.

`agent.prompt_microkernel` exposes the five stable handles (`recall`,
`inspect`, `decide`, `act`, `verify`) and loads primitive schemas only when a
caller builds a capsule. The fixed primitive schema is capped at 1 KiB, the
fixture capsule is below 2,000 rough tokens, and `CapabilityParityReceipt`
records missing/extra capabilities without changing the existing #196 full-set
pinning behavior. Context IDs and cache receipts are opaque content hashes;
they preserve the stable prefix and never contain prompt text.

The representative route fixture measures the local contract only: its
routine routes are at least 80% remote-free. This is a deterministic fixture
receipt, not a provider billing or latency claim.
