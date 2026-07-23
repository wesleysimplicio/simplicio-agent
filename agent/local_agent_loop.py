"""Small cache-aware local-agent orchestration seam.

This module deliberately composes existing prompt, Runtime and tool-batch
contracts. It does not choose providers or bypass Runtime authorization.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from agent.prompt_zones import InferenceLease, LeaseReceipt, PromptZones, RuntimeLeaseTransport
from tools.tool_call_batch import BatchResult, ToolCall, ToolSpec, classify_batch, execute_tool_call_batch

ToolHandler = Callable[[ToolCall], Any]


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
    ) -> None:
        self._zones = zones
        self._registry = registry
        self._lease = InferenceLease(session_id, zones, transport)

    @property
    def lease_receipt(self) -> LeaseReceipt | None:
        return self._lease.receipt

    def run_turn(self, payload: str | bytes | bytearray, handler: ToolHandler) -> LocalTurnResult:
        lease = self._lease.acquire()
        calls = self._parse(payload)
        results = execute_tool_call_batch(payload, self._registry, handler)
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
        )
        return LocalTurnResult(results=results, receipt=receipt)

    def close(self) -> None:
        self._lease.finish()

    def __enter__(self) -> "LocalAgentLoop":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.close()

    def _parse(self, payload: str | bytes | bytearray) -> tuple[ToolCall, ...]:
        from tools.tool_call_batch import parse_tool_call_batch

        return parse_tool_call_batch(payload, self._registry)


def receipt_json(result: LocalTurnResult) -> str:
    """Serialize only the redacted receipt, with stable key ordering."""

    return json.dumps(result.receipt.to_dict(), sort_keys=True, separators=(",", ":"))


__all__ = ["LocalAgentLoop", "LocalTurnReceipt", "LocalTurnResult", "receipt_json"]
