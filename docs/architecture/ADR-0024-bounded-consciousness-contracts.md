# ADR-0024: Bounded Consciousness Contracts

Status: accepted slice

## Decision

Issues #169, #170, and #171 are represented by mechanical contracts, not a
claim of subjective consciousness. `agent.attention_schema` assigns priority
from a closed reason enum and selects a fixed-budget workspace deterministically;
untrusted content has no priority field to manipulate. Safety and approvals
preempt normal work, duplicate background events retain receipt references, and
open loops close only with a completion, cancellation, or supersession receipt.

`agent.prediction_receipts` remains the pre-action prediction and counterfactual
contract. Its canonical JSON now also yields a SHA-256 evidence reference, so
memory can cite a prediction without copying expected values, action arguments,
or counterfactual content.

`agent.autobiographical_memory` accepts verified episode manifests rather than
raw transcripts. Consolidation stores sanitized summaries and receipt hashes,
uses explicit valid/system time, supersedes instead of overwriting, and supports
revocation. Runtime/self memory rejects personal facts, external acquisition
cannot promote directly, poisoned facts are ignored, and user preferences need
a consent receipt.

## Boundaries

This slice does not authorize actions, mutate prompts, integrate transport or
operational-now, or expose chain-of-thought. Integration with the action gate,
persistent provider storage, watcher/effect journal, UI, and cross-run benchmark
harnesses remains external follow-up work; these modules fail closed without
those integrations.
