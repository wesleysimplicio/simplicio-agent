"""Small cache-aware local-agent orchestration seam.

This module deliberately composes existing prompt, Runtime and tool-batch
contracts. It does not choose providers or bypass Runtime authorization.
"""

from __future__ import annotations

import json
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from agent.no_progress_guard import GuardAction, NoProgressGuard
from agent.prompt_zones import (
    InferenceLease,
    LeaseReceipt,
    PromptZones,
    RuntimeLeaseTransport,
)
from agent.telemetry.receipts import record_receipt
from tools.tool_call_batch import (
    BatchResult,
    ToolCall,
    ToolSpec,
    build_gbnf,
    classify_batch,
    execute_tool_call_batch,
)

ToolHandler = Callable[[ToolCall], Any]
EvaluationHook = Callable[[Mapping[str, Any]], Any]
_COMPACT_STATE_KEYS = (
    "generation",
    "snapshot_ref",
    "snapshot_bytes",
    "token_budget",
    "node_count",
    "actions",
    "text",
    "vision_escalation",
)


@dataclass(frozen=True)
class LocalTurnReceipt:
    """Redacted, deterministic evidence for one local loop turn."""

    schema: str
    session_id: str
    prefix_sha256: str
    generation: int
    lease_id: str
    call_ids: tuple[str, ...]
    tools: tuple[str, ...]
    parallel: bool
    ok: bool
    grammar_sha256: str = ""
    schema_prefix_sha256: str = ""
    schema_expansions: tuple[Mapping[str, Any], ...] = ()
    guard_decisions: tuple[Mapping[str, Any], ...] = ()
    recovery: str | None = None
    browser_state: Mapping[str, Any] | None = None
    receipt_sha: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "session_id": self.session_id,
            "prefix_sha256": self.prefix_sha256,
            "generation": self.generation,
            "lease_id": self.lease_id,
            "call_ids": list(self.call_ids),
            "tools": list(self.tools),
            "parallel": self.parallel,
            "ok": self.ok,
            "grammar_sha256": self.grammar_sha256,
            "schema_prefix_sha256": self.schema_prefix_sha256,
            "schema_expansions": [dict(item) for item in self.schema_expansions],
            "guard_decisions": [dict(item) for item in self.guard_decisions],
            "recovery": self.recovery,
            "browser_state": dict(self.browser_state)
            if self.browser_state is not None
            else None,
            "receipt_sha": self.receipt_sha,
        }


@dataclass(frozen=True)
class LocalTurnResult:
    results: tuple[BatchResult, ...]
    receipt: LocalTurnReceipt


class LocalAgentLoop:
    """Bind a prompt prefix and Runtime lease for a bounded local session."""

    def __init__(
        self,
        session_id: str,
        zones: PromptZones,
        transport: RuntimeLeaseTransport,
        registry: Mapping[str, ToolSpec],
        *,
        schema_catalog: Any | None = None,
        no_progress_guard: NoProgressGuard | None = None,
        receipt_directory: Path | None = None,
        evaluation_hook: EvaluationHook | None = None,
    ) -> None:
        self._zones = zones
        self._registry = registry
        self._lease = InferenceLease(session_id, zones, transport)
        self._schema_catalog = schema_catalog
        self._no_progress_guard = no_progress_guard or NoProgressGuard()
        self._receipt_directory = receipt_directory
        self._evaluation_hook = evaluation_hook

    @property
    def lease_receipt(self) -> LeaseReceipt | None:
        return self._lease.receipt

    def run_turn(
        self,
        payload: str | bytes | bytearray,
        handler: ToolHandler,
        *,
        browser_state: Mapping[str, Any] | None = None,
    ) -> LocalTurnResult:
        lease = self._lease.acquire()
        calls = self._parse(payload)
        grammar_sha256 = hashlib.sha256(
            build_gbnf(self._registry).encode("utf-8")
        ).hexdigest()
        schema_prefix_sha256, schema_expansions = self._expand_schemas(calls)

        guard_decisions = [
            self._no_progress_guard.before_call(call.name, call.args).to_dict()
            for call in calls
        ]
        blocked = next(
            (
                decision
                for decision in guard_decisions
                if decision["action"]
                in {
                    GuardAction.VETO.value,
                    GuardAction.REPLAN.value,
                    GuardAction.TERMINATE.value,
                }
            ),
            None,
        )
        if blocked is not None:
            results = tuple(
                BatchResult(
                    call.call_id,
                    call.name,
                    False,
                    error=f"no_progress:{blocked['action']}",
                )
                for call in calls
            )
            recovery = str(blocked["action"])
        else:
            results = execute_tool_call_batch(payload, self._registry, handler)
            recovery = None
            for call, result in zip(calls, results):
                decision = self._no_progress_guard.record_result(
                    call.name,
                    call.args,
                    result.value if result.ok else result.error,
                    evidence_count=sum(item.ok for item in results),
                    failure_code=result.error or "",
                )
                guard_decisions.append(decision.to_dict())
                if decision.action in {GuardAction.REPLAN, GuardAction.TERMINATE}:
                    recovery = decision.action.value

        compact_state = self._compact_browser_state(browser_state, results)
        summary = {
            "schema": "simplicio.local-agent-turn-summary/v1",
            "session_id": lease.session_id,
            "prefix_sha256": lease.prefix_sha256,
            "generation": lease.generation,
            "lease_id": lease.lease_id,
            "calls": [{"id": call.call_id, "tool": call.name} for call in calls],
            "results": [
                {
                    "id": result.call_id,
                    "tool": result.tool,
                    "ok": result.ok,
                    "error": result.error,
                }
                for result in results
            ],
            "parallel": classify_batch(calls, self._registry),
            "recovery": recovery,
        }
        stored_receipt = record_receipt(
            payload=json.dumps(summary, sort_keys=True, separators=(",", ":")),
            yool_id=f"agent.local.{lease.session_id}",
            lane="fast",
            status="ok" if all(result.ok for result in results) else "error",
            meta={
                "turn_schema": "simplicio.local-agent-turn-receipt/v1",
                "lease_id": lease.lease_id,
            },
            directory=self._receipt_directory,
        )
        receipt = LocalTurnReceipt(
            schema="simplicio.local-agent-turn-receipt/v1",
            session_id=lease.session_id,
            prefix_sha256=lease.prefix_sha256,
            generation=lease.generation,
            lease_id=lease.lease_id,
            call_ids=tuple(call.call_id for call in calls),
            tools=tuple(call.name for call in calls),
            parallel=classify_batch(calls, self._registry),
            ok=all(result.ok for result in results),
            grammar_sha256=grammar_sha256,
            schema_prefix_sha256=schema_prefix_sha256,
            schema_expansions=tuple(schema_expansions),
            guard_decisions=tuple(guard_decisions),
            recovery=recovery,
            browser_state=compact_state,
            receipt_sha=stored_receipt.sha,
        )
        result = LocalTurnResult(results=results, receipt=receipt)
        if self._evaluation_hook is not None:
            self._evaluation_hook({
                "schema": "simplicio.local-agent-evaluation/v1",
                "session_id": lease.session_id,
                "status": "completed" if receipt.ok else "error",
                "steps": len(calls),
                "evidence": [receipt.receipt_sha],
                "validation": "passed" if receipt.ok else "failed",
                "receipt": receipt.to_dict(),
            })
        return result

    def close(self) -> None:
        self._lease.finish()

    def __enter__(self) -> "LocalAgentLoop":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.close()

    def _parse(self, payload: str | bytes | bytearray) -> tuple[ToolCall, ...]:
        from tools.tool_call_batch import parse_tool_call_batch

        return parse_tool_call_batch(payload, self._registry)

    def _expand_schemas(
        self, calls: tuple[ToolCall, ...]
    ) -> tuple[str, tuple[Mapping[str, Any], ...]]:
        if self._schema_catalog is None:
            return "", ()
        prefix = self._schema_catalog.stable_prefix()
        prefix_bytes = json.dumps(prefix, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
        expansions = []
        for call in calls:
            expanded = self._schema_catalog.expand_with_receipt(call.name)
            receipt = getattr(expanded, "receipt", None)
            if receipt is None:
                continue
            as_dict = getattr(receipt, "as_dict", None) or getattr(
                receipt, "to_dict", None
            )
            if callable(as_dict):
                expansions.append(as_dict())
        return hashlib.sha256(prefix_bytes).hexdigest(), tuple(expansions)

    @staticmethod
    def _compact_browser_state(
        browser_state: Mapping[str, Any] | None,
        results: tuple[BatchResult, ...],
    ) -> Mapping[str, Any] | None:
        candidates: list[Any] = [browser_state]
        for result in results:
            value = result.value
            if isinstance(value, Mapping):
                candidates.append(value.get("compact_state"))
            elif isinstance(value, str):
                try:
                    decoded = json.loads(value)
                except (TypeError, ValueError):
                    decoded = None
                if isinstance(decoded, Mapping):
                    candidates.append(decoded.get("compact_state"))
        for candidate in candidates:
            if isinstance(candidate, Mapping):
                return {
                    key: candidate[key]
                    for key in _COMPACT_STATE_KEYS
                    if key in candidate
                }
        return None


def receipt_json(result: LocalTurnResult) -> str:
    """Serialize only the redacted receipt, with stable key ordering."""

    return json.dumps(result.receipt.to_dict(), sort_keys=True, separators=(",", ":"))


__all__ = ["LocalAgentLoop", "LocalTurnReceipt", "LocalTurnResult", "receipt_json"]
