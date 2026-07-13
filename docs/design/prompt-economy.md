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
