# Context Working-Set

The working-set keeps a small, cheap **hot** set of context handles in memory
and stashes full payloads in a **cold-ref** store. Handles are only expanded
(loaded back into the hot set) when the agent actually needs them — so the
per-turn system prompt stays small and token cost is paid only for touched
handles.

Built 2026-07-13 in Simplicio Agent (Turbo issue #92 was spec-only in upstream;
neither repo had the code). Stdlib-only, no LLM round-trip on the mechanical
path.

## Modules (`agent/context/`)

| File | Responsibility |
|------|----------------|
| `working_set.py` | `WorkingSet` — LRU-capped hot set over `Handle`s; `expand(handle)` loads from `ColdStore`. `ColdStore` is the pluggable cold backend (in-memory default; subclass for disk/db). |
| `retrieval.py` | `TfidfScorer` — pure-Python TF-IDF to rank which cold handles are relevant to a query. |
| `token_cache.py` | `TokenCache` — model-scoped, blake2b-keyed, LRU-capped cache of encoded token sequences. |
| `incremental.py` | `IncrementalPipeline` — wires scorer + working set: `register(id, text, payload)` indexes cold text; `prefetch(query)` promotes the top-`k` relevant cold handles into the hot set. |

## API sketch

```python
from agent.context import IncrementalPipeline

pipe = IncrementalPipeline(prefetch_k=4)
pipe.register("rust_doc", "rust cargo build release profile lto", "RUST_PAYLOAD")
pipe.register("py_doc",  "python pip install requirements",      "PY_PAYLOAD")

# before a turn, prefetch what the user query is likely to need
promoted = pipe.prefetch("compile a rust release with cargo")
assert "rust_doc" in promoted

# later, expand on demand (no LLM cost to decide)
payload = pipe.expand("rust_doc")
```

## Tests

`tests/test_working_set.py` — 12 cases: LRU eviction keeps cold-ref, cold hit
promotes, TF-IDF ranking prefers term overlap, token cache is model-scoped and
LRU-evicts, pipeline prefetch promotes only relevant handles.

Run:

```bash
./venv/bin/python -m pytest tests/test_working_set.py -q
```

(If `pytest` is not installed in the venv, the test functions are plain
`test_*` callables and can be driven by any runner.)

## Native context IDs and cache receipts

The bounded #318 slice adds `WorkingSet.snapshot()` and `WorkingSet.delta()`.
Snapshots contain only opaque BLAKE2b content IDs; deltas sort `added`,
`changed`, and `removed` keys and include a deterministic digest, so unchanged
context can be skipped without rereading its bytes. `TokenCache` provides
`get_with_receipt()` and `put_with_receipt()` for model-scoped cache evidence;
the receipt contains only the model label, content key, hit flag, and token
count. These helpers are additive and preserve the existing `get`/`put` API.
