# ADR-0009: Adaptive neural skill recall on the turn hot path

**Status:** Accepted (2026-07-13).  
**Owner:** @wesleysimplicio.  
**Code:** `plugins/simplicio/skill_recall.py`, `plugins/simplicio/__init__.py`, `tests/plugins/test_simplicio_skill_recall.py`.  
**Related:** `AGENTS.md#tool-routing`, ADR-0007, ADR-0003.

## Context

Simplicio Agent can expose hundreds of installed skills. Loading every `SKILL.md` into every request makes the prompt larger, invalidates useful cache assumptions, increases latency, and makes unrelated procedures compete for attention. Merely storing skills in SQLite does not solve this: before this decision the live database contained hundreds of enabled rows but ordinary task wording could still return no useful skill, and no `skill_load_events` were recorded.

The user requirement is to let the whole catalog participate in every non-trivial task while paying only for the smallest useful subset.

## Decision

The bundled `simplicio` plugin owns an adaptive, fail-open neural skill selector on `pre_llm_call`.

For each user turn it:

1. tokenizes the user intent and expands a bounded bilingual synonym set;
2. ranks all enabled `skills_registry` entries against catalog title/content;
3. injects only skill handles, never full skill bodies;
4. chooses zero to three handles adaptively;
5. leaves the exact procedure behind the existing `skill_view` interface;
6. records successful/failed `skill_view` calls in `skill_load_events`.

Selection budget:

| Intent state | Injected skills |
|---|---:|
| Trivial/conversational | 0 |
| Clear winner (`lead >= 2.0`, gap `>= 0.75`) | 1 |
| Moderate confidence (`lead >= 1.5`, gap `>= 0.30`) | 2 |
| Genuine ambiguity | at most 3 |

The injected context is intentionally small:

```text
Skill recall: `<handle>`. Load only applicable candidates with skill_view.
```

The plugin does not replace reasoning, repository orientation, source reading, or the execution policy in [`AGENTS.md#tool-routing`](../../AGENTS.md#tool-routing). It only selects reusable procedures.

## Module boundary

`plugins/simplicio/skill_recall.py` is a deep module with a narrow interface:

- `recall(message, k)` — deterministic ranked candidates;
- `_pre_llm_call(...)` — compact candidate context or `None`;
- `_post_tool_call(...)` — usage telemetry;
- `register_skill_recall(ctx)` — hook registration.

The existing `simplicio` plugin remains the single user-facing toggle. A second required plugin would create configuration drift between local bundles and the repository.

## Performance contract

The catalog is read and pre-tokenized once per process through an in-memory cache. Database writes are limited to actual `skill_view` outcomes.

Measured on the development MacBook with 605 enabled registry rows:

| Metric | Before | Accepted implementation |
|---|---:|---:|
| Warm recall median | 176.723 ms | 1.078 ms |
| Warm recall p95 | not measured | 2.518 ms |
| First catalog load | implicit every turn | 376.818 ms once/process |
| Clear-winner context | multi-candidate prose | 27 `cl100k_base` tokens |

These are development-host measurements, not universal product guarantees. Regression tests assert behavior; benchmarks/telemetry should track production distributions.

## Cache and consistency

Catalog mutations become visible after process restart or explicit cache clear. This is acceptable because skill installation/removal already requires a session/plugin refresh for prompt-level availability. The hot path must not reopen and retokenize the whole catalog each turn.

Prompt-cache invariants are preserved: the static system prompt and tool schemas do not change. Candidate handles are ephemeral turn context, and full skill bodies are loaded only when selected.

## Failure and safety behavior

Recall is fail-open:

- missing SQLite database → no injected context;
- SQLite read/write error → conversation continues;
- empty/trivial message → no injected context;
- irrelevant candidates may be ignored by the model;
- `SIMPLICIO_PLUGIN_DISABLE=1` disables the whole plugin;
- `SIMPLICIO_SKILL_RECALL_DISABLE=1` disables recall only.

No skill body is executed automatically. Selection still requires `skill_view`, preserving existing validation and prompt-injection defenses around skill loading.

## Consequences

### Positive

- every enabled skill can participate in routing without entering every prompt;
- clear tasks normally pay for one handle and one skill body;
- trivial conversation pays zero skill-context overhead;
- load telemetry enables later quality feedback, deduplication, and decay;
- local profile behavior and repository behavior share one implementation.

### Costs

- first use pays a one-time catalog load;
- lexical/synonym ranking is not equivalent to a semantic embedding model;
- process restart is required after catalog mutation;
- `skill_load_events` records loading, not task success causality.

## Rejected alternatives

1. **Load every skill every turn:** rejected for prompt size, cache pressure, and attention dilution.
2. **Fixed top-3:** rejected because clear intents paid for unnecessary candidates.
3. **Put recall in a separate required plugin:** rejected because it creates a second enablement contract and local/repo drift.
4. **Inject descriptions and scores:** rejected because handles are sufficient; scores are telemetry, not reasoning context.
5. **Make a model classify skills:** rejected on the hot path because it adds latency, cost, and another failure mode before the primary model call.

## Follow-ups

- Add outcome attribution beyond `loaded/error` so ranking can learn from verified task completion.
- Add catalog versioning/invalidation instead of restart-only refresh.
- Add language-independent semantic fallback when lexical confidence is low, without placing another paid model on the hot path.
- Add a benchmark fixture for catalog sizes 100/600/2,000 and enforce a warm-latency budget in CI where stable timing is available.
- Retire the temporary user-level `neural-skill-recall` plugin after the updated bundle is deployed; the bundled `simplicio` plugin becomes canonical.
