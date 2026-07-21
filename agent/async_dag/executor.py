"""Dependency-aware async tool batch executor.

Upstream Hermes already parallelises independent tools (``parallel_tool_batch``
showed ~5× over sequential). But it does not *infer* dependencies: callers
must declare batches manually. This module adds a DAG resolver that:

1. Accepts a list of ``DagNode`` (one per planned tool call).
2. Computes topological levels via Kahn's algorithm.
3. Runs each level in parallel via ``asyncio.gather``.
4. Feeds outputs of upstream nodes into placeholders inside downstream
   arguments (``$ref:<node_id>``).

Pure stdlib (``asyncio``, ``collections``). No external scheduler. Errors
short-circuit the level they happen on and surface as ``DagError``.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Mapping, Optional, Sequence

from agent.model_metadata import estimate_tokens_rough
from agent.possibility_ledger import assert_shrinking_delegation
from agent.telemetry.receipts import Receipt, record_receipt


class DagError(RuntimeError):
    """Raised when the DAG cannot be built (cycle, missing dep, etc.)."""


ToolCallable = Callable[[str, Mapping[str, Any]], Awaitable[Any]]


@dataclass(frozen=True)
class DagNode:
    """One planned tool invocation.

    ``args`` may contain references of the form ``"$ref:<other_node_id>"``
    (string-typed) or ``{"$ref": "<other_node_id>"}`` (dict-typed). The
    executor resolves them to the corresponding upstream output before
    invoking ``tool``.
    """

    node_id: str
    tool: str
    args: Mapping[str, Any] = field(default_factory=dict)
    depends_on: tuple[str, ...] = ()
    yool_id: str = "agent.async_dag"
    depth: int = 0
    input_context: str | None = None

    @property
    def tuple_hash(self) -> str:
        """Return the deterministic tuple identity for this node."""

        payload = json.dumps(
            {
                "yool_id": self.yool_id,
                "node_id": self.node_id,
                "tool": self.tool,
                "args": self.args,
                "depends_on": self.depends_on,
                "depth": self.depth,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=repr,
        ).encode("utf-8")
        return hashlib.blake2b(payload, digest_size=32).hexdigest()

    @property
    def identity(self) -> str:
        return f"{self.yool_id}:{self.tuple_hash}"


@dataclass
class DagResult:
    outputs: Dict[str, Any]
    errors: Dict[str, BaseException]
    levels: List[List[str]]
    elapsed_s: float
    receipts: Dict[str, Receipt] = field(default_factory=dict)
    max_resident: int = 0
    peak_resident: int = 0

    @property
    def ok(self) -> bool:
        return not self.errors

    def as_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "node_count": len(self.outputs) + len(self.errors),
            "errors": {k: repr(v) for k, v in self.errors.items()},
            "levels": [list(level) for level in self.levels],
            "elapsed_s": round(self.elapsed_s, 4),
            "max_resident": self.max_resident,
            "peak_resident": self.peak_resident,
            "receipts": {
                node_id: {
                    "sha": receipt.sha,
                    "yool_id": receipt.yool_id,
                    "tokens": receipt.cost.tokens,
                    "tokens_raw": receipt.cost.tokens_raw,
                    "tokens_saved": receipt.cost.tokens_saved,
                }
                for node_id, receipt in self.receipts.items()
            },
        }


def _topo_levels(nodes: Sequence[DagNode]) -> List[List[str]]:
    """Group nodes into topological levels using Kahn's algorithm."""

    by_id: Dict[str, DagNode] = {n.node_id: n for n in nodes}
    if len(by_id) != len(nodes):
        raise DagError("duplicate node_id")

    indeg: Dict[str, int] = {n.node_id: 0 for n in nodes}
    children: Dict[str, List[str]] = defaultdict(list)
    for n in nodes:
        for dep in n.depends_on:
            if dep not in by_id:
                raise DagError(f"node {n.node_id} depends on unknown {dep!r}")
            indeg[n.node_id] += 1
            children[dep].append(n.node_id)

    ready = deque(nid for nid, d in indeg.items() if d == 0)
    levels: List[List[str]] = []
    visited = 0
    while ready:
        level = list(ready)
        ready.clear()
        levels.append(level)
        for nid in level:
            visited += 1
            for child in children[nid]:
                indeg[child] -= 1
                if indeg[child] == 0:
                    ready.append(child)

    if visited != len(nodes):
        raise DagError("cycle detected in DAG")
    return levels


def _resolve_refs(value: Any, outputs: Mapping[str, Any]) -> Any:
    if isinstance(value, str) and value.startswith("$ref:"):
        ref = value[5:]
        if ref not in outputs:
            raise DagError(f"unresolved $ref:{ref}")
        return outputs[ref]
    if isinstance(value, dict):
        if "$ref" in value and len(value) == 1:
            ref = value["$ref"]
            if not isinstance(ref, str) or ref not in outputs:
                raise DagError(f"unresolved $ref dict {value!r}")
            return outputs[ref]
        return {k: _resolve_refs(v, outputs) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_refs(v, outputs) for v in value]
    return value


def build_dag(nodes: Sequence[DagNode]) -> List[List[str]]:
    """Public helper — returns topo levels without executing."""

    return _topo_levels(list(nodes))


@dataclass
class DagExecutor:
    dispatch: ToolCallable
    max_concurrency: int = 16
    max_resident: Optional[int] = None
    max_depth: Optional[int] = None
    receipt_directory: Optional[Path] = None

    async def run(self, nodes: Sequence[DagNode]) -> DagResult:
        if self.max_concurrency < 1:
            raise ValueError("max_concurrency must be positive")
        if self.max_resident is not None and self.max_resident < 1:
            raise ValueError("max_resident must be positive")
        resident_limit = (
            self.max_resident if self.max_resident is not None else self.max_concurrency
        )
        if resident_limit < 1:
            raise ValueError("max_resident must be positive")
        if self.max_depth is not None and self.max_depth < 1:
            raise ValueError("max_depth must be positive")

        loop = asyncio.get_event_loop()
        t0 = loop.time()
        by_id: Dict[str, DagNode] = {n.node_id: n for n in nodes}
        levels = _topo_levels(list(nodes))
        outputs: Dict[str, Any] = {}
        errors: Dict[str, BaseException] = {}
        receipts: Dict[str, Receipt] = {}
        state_lock = asyncio.Lock()
        resident = 0
        peak_resident = 0

        async def _run_one(node_id: str) -> None:
            nonlocal resident, peak_resident
            node = by_id[node_id]
            if self.max_depth is not None and node.depth >= self.max_depth:
                errors[node_id] = DagError(
                    f"recursion depth limit reached for {node_id}: "
                    f"depth={node.depth}, max_depth={self.max_depth}"
                )
                return
            if any(dep in errors for dep in node.depends_on):
                errors[node_id] = DagError(f"upstream dep failed for {node_id}")
                return
            try:
                resolved = _resolve_refs(node.args, outputs)
                async with state_lock:
                    resident += 1
                    peak_resident = max(peak_resident, resident)
                try:
                    result = await self.dispatch(node.tool, resolved)
                finally:
                    async with state_lock:
                        resident -= 1

                if node.input_context is not None:
                    summary = (
                        result.get("summary") if isinstance(result, Mapping) else result
                    )
                    if not isinstance(summary, str):
                        raise DagError(
                            f"node {node_id} did not return a string summary"
                        )
                    try:
                        assert_shrinking_delegation(
                            node.input_context,
                            summary,
                            receipt_directory=self.receipt_directory,
                        )
                    except ValueError as exc:
                        raise DagError(str(exc)) from exc

                input_blob = json.dumps(
                    {"identity": node.identity, "args": resolved},
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    default=repr,
                )
                output_blob = json.dumps(
                    result,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    default=repr,
                )
                raw_tokens = max(1, estimate_tokens_rough(input_blob + output_blob))
                output_tokens = max(1, estimate_tokens_rough(output_blob))
                receipts[node_id] = record_receipt(
                    payload=input_blob + "\n" + output_blob,
                    yool_id=node.yool_id,
                    lane="fast",
                    status="ok",
                    tokens=output_tokens,
                    tokens_raw=raw_tokens,
                    tokens_saved=max(0, raw_tokens - output_tokens),
                    directory=self.receipt_directory,
                    meta={
                        "proof_kind": "dag_node_execution",
                        "node_id": node.node_id,
                        "tuple_hash": node.tuple_hash,
                    },
                )
                outputs[node_id] = result
            except BaseException as exc:  # noqa: BLE001
                errors[node_id] = exc

        async def _run_level(level: List[str]) -> None:
            queue: asyncio.Queue[str] = asyncio.Queue()
            for node_id in level:
                queue.put_nowait(node_id)

            worker_count = min(self.max_concurrency, resident_limit, len(level))

            async def worker() -> None:
                while True:
                    try:
                        node_id = queue.get_nowait()
                    except asyncio.QueueEmpty:
                        return
                    try:
                        await _run_one(node_id)
                    finally:
                        queue.task_done()

            await asyncio.gather(*(worker() for _ in range(worker_count)))

        for level in levels:
            await _run_level(level)

        return DagResult(
            outputs=outputs,
            errors=errors,
            levels=levels,
            elapsed_s=loop.time() - t0,
            receipts=receipts,
            max_resident=resident_limit,
            peak_resident=peak_resident,
        )
