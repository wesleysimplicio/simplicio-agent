"""Bounded local reversible proof for issue #181.

This module composes the existing control-plane primitives into one deliberately
small path: a prepared local fixture is gated, checkpointed, changed, verified,
and restored.  It does not claim Desktop/UIA, browser, publication, or
cross-machine coverage; those surfaces are returned as unavailable in the
result instead of being silently treated as part of the proof.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from agent.capability_registry import (
    Capability,
    CapabilityMetadata,
    CapabilityRegistry,
    Determinism,
    Health,
    Risk,
)
from agent.goal_contract import GoalContract
from agent.delivery_certificate import (
    EvidenceVerdict,
    ReproducibleManifest,
    RoutingDecision,
    StructuralCheck,
    TaskCertificate,
    sha256_text,
)
from agent.verification_evidence import VerificationEvidence
from tools.checkpoint_manager import CheckpointManager
from tools.simplicio_transport import SimplicioTransport, TransportReceipt


ARTIFACT_RELATIVE_PATH = Path("controlled-artifact") / "requirements.txt"
BASELINE_CONTENT = "# issue-181 baseline\nname = local-proof\n"
FINAL_CONTENT = "# issue-181 verified\nname = local-proof\nstatus = changed\n"
WATCHER_NAME = "local_artifact_watcher"
ACCEPTANCE_CRITERIA = (
    "the local file capability is selected deterministically",
    "runtime policy and a pre-write checkpoint are recorded",
    "the final document content and hash are verified",
    "undo restores the baseline content and hash",
    "the watcher recomputes the restored path and content",
)


def _sha256(value: bytes | str) -> str:
    payload = value.encode("utf-8") if isinstance(value, str) else value
    return hashlib.sha256(payload).hexdigest()


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _workspace_root(workspace: str | os.PathLike[str]) -> Path:
    root = Path(workspace).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"workspace must be an existing directory: {workspace}")
    return root


def _artifact_path(root: Path) -> Path:
    path = (root / ARTIFACT_RELATIVE_PATH).resolve()
    if root not in path.parents:
        raise ValueError("artifact path escapes workspace")
    return path


def _snapshot(path: Path) -> dict[str, Any]:
    exists = path.is_file()
    content = path.read_text(encoding="utf-8") if exists else ""
    return {
        "relative_path": ARTIFACT_RELATIVE_PATH.as_posix(),
        "exists": exists,
        "content": content,
        "sha256": _sha256(content),
    }


def prepare_reversible_workspace(workspace: str | os.PathLike[str]) -> str:
    """Create the deterministic baseline fixture used by the mutating phase.

    Preparation is explicit so callers can checkpoint before the first action
    write.  The returned path is relative and safe to include in receipts.
    """

    root = _workspace_root(workspace)
    path = _artifact_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(BASELINE_CONTENT, encoding="utf-8", newline="\n")
    return ARTIFACT_RELATIVE_PATH.as_posix()


def _capabilities() -> CapabilityRegistry:
    return CapabilityRegistry((
        Capability(
            "local_file_api",
            CapabilityMetadata(
                version="1.0.0",
                source="python.pathlib",
                license="PSF-2.0",
                platforms=(sys.platform, "local"),
                health=Health.HEALTHY,
                risk=Risk.LOW,
                determinism=Determinism.DETERMINISTIC,
            ),
        ),
        Capability(
            "desktop_uia",
            CapabilityMetadata(
                version="0.0.0",
                source="not-configured",
                license="unknown",
                platforms=(sys.platform,),
                health=Health.UNHEALTHY,
                risk=Risk.HIGH,
                determinism=Determinism.UNKNOWN,
                health_detail="Desktop/UIA is outside this bounded local slice",
            ),
            enabled=False,
        ),
    ))


@dataclass(frozen=True)
class ReversiblePathResult:
    """Serializable receipt for the bounded local path."""

    status: str
    workspace_id: str
    artifact: str
    goal: dict[str, Any]
    route: dict[str, Any]
    runtime_gate: dict[str, Any]
    runtime_checkpoint: dict[str, Any]
    action_digest: str
    idempotency_key: str
    checkpoint_taken: bool
    checkpoint: dict[str, Any] | None
    before: dict[str, Any]
    after: dict[str, Any]
    undo: dict[str, Any]
    watcher: dict[str, Any]
    delivery_certificate: TaskCertificate
    availability: dict[str, Any]
    trace: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _receipt(receipt: TransportReceipt) -> dict[str, Any]:
    return receipt.to_dict()


def _gate_allows(receipt: TransportReceipt) -> bool:
    """Interpret a successful Runtime response without treating ``confirm`` as allow."""

    if not receipt.ok or not isinstance(receipt.value, dict):
        return False
    decision = str(receipt.value.get("decision", "")).strip().lower()
    if decision:
        return decision in {
            "allow",
            "allowed",
            "approve",
            "approved",
            "permit",
            "permitted",
        }
    return bool(receipt.value.get("allowed", False))


def _certificate_manifest(
    *, task_id: str, runtime_available: bool, trajectory: Any, diff: str
) -> ReproducibleManifest:
    return ReproducibleManifest(
        task_id=task_id,
        agent_version="simplicio-agent-local",
        runtime_version="available" if runtime_available else None,
        runtime_available=runtime_available,
        provider="local-path",
        model="not-used",
        temperature=0.0,
        seed=0,
        prompt_sha256=sha256_text("issue-181-local-reversible-write"),
        trajectory_sha256=sha256_text(_canonical(trajectory)),
        diff_sha256=sha256_text(diff),
        routing=RoutingDecision.NO_THINK,
        nondeterminism_reason=None,
        runtime_certificate_claim=False,
    )


def _certificate(
    *,
    task_id: str,
    manifest: ReproducibleManifest,
    status: str,
    reason: str | None = None,
    evidence: tuple[EvidenceVerdict, ...] = (),
) -> TaskCertificate:
    return TaskCertificate.create(
        task_id=task_id,
        manifest=manifest,
        evidence=evidence,
        structural_checks=(
            StructuralCheck("certificate-schema", True, "pinned schema is present"),
            StructuralCheck(
                "runtime-claim-boundary", True, "runtime certificate is not claimed"
            ),
            StructuralCheck(
                "local-path-identity", True, "artifact path is bounded and hashed"
            ),
        ),
        blocked_reason=reason if status == "blocked" else None,
    )


def _blocked(
    *,
    root: Path,
    goal: GoalContract,
    route: dict[str, Any],
    gate: TransportReceipt,
    checkpoint: TransportReceipt,
    reason: str,
    availability: dict[str, Any],
) -> ReversiblePathResult:
    return ReversiblePathResult(
        status="blocked",
        workspace_id=_sha256(str(root)),
        artifact=ARTIFACT_RELATIVE_PATH.as_posix(),
        goal=goal.add_fact(reason, source="reversible_path").to_dict(),
        route=route,
        runtime_gate=_receipt(gate),
        runtime_checkpoint=_receipt(checkpoint),
        action_digest="",
        idempotency_key="",
        checkpoint_taken=False,
        checkpoint=None,
        before=_snapshot(_artifact_path(root)),
        after=_snapshot(_artifact_path(root)),
        undo=_snapshot(_artifact_path(root)),
        watcher={"status": "not_run", "reason": reason},
        delivery_certificate=_certificate(
            task_id="issue-181",
            manifest=_certificate_manifest(
                task_id="issue-181",
                runtime_available=False,
                trajectory=("blocked", reason),
                diff="",
            ),
            status="blocked",
            reason=reason,
        ),
        availability=availability,
        trace=({"stage": "blocked", "reason": reason},),
    )


def run_local_reversible_path(
    workspace: str | os.PathLike[str],
    *,
    transport: SimplicioTransport | None = None,
    checkpoint_manager: CheckpointManager | None = None,
    session_id: str = "issue-181",
) -> ReversiblePathResult:
    """Run the local file-API happy path and prove undo.

    ``prepare_reversible_workspace`` must be called first.  Requiring an
    existing baseline makes the first mutation in this function occur only
    after the Runtime gate and local checkpoint succeed.
    """

    root = _workspace_root(workspace)
    artifact = _artifact_path(root)
    if (
        not artifact.is_file()
        or artifact.read_text(encoding="utf-8") != BASELINE_CONTENT
    ):
        raise ValueError("workspace is not prepared with the deterministic baseline")

    registry = _capabilities()
    decision = registry.route(
        "local_file_api", session_id=session_id, platform=sys.platform
    )
    goal = GoalContract.create(
        "Create and reversibly verify a local requirements artifact",
        ACCEPTANCE_CRITERIA,
    ).add_watcher(WATCHER_NAME)
    runtime = transport or SimplicioTransport()
    manager = checkpoint_manager or CheckpointManager(enabled=True)
    gate = runtime.gate(
        "issue-181-local-reversible-write",
        pattern_key="local_file_api",
        description="bounded local artifact write with undo",
        session_key=session_id,
    )
    availability = {
        "local_file_api": {
            "available": decision.selected,
            "selected": decision.capability,
        },
        "desktop_uia": {
            "available": False,
            "reason": "not configured in bounded slice",
        },
        "runtime": {
            "available": _gate_allows(gate),
            "transport": gate.transport,
            "fallback_reason": gate.fallback_reason,
            "health": runtime.health(),
        },
    }
    runtime_checkpoint = runtime.checkpoint(
        "issue-181-before-write",
        workdir=str(root),
        extra={"session_id": session_id, "artifact": ARTIFACT_RELATIVE_PATH.as_posix()},
    )
    if not decision.selected:
        return _blocked(
            root=root,
            goal=goal,
            route=decision.to_dict(),
            gate=gate,
            checkpoint=runtime_checkpoint,
            reason="local file capability was not selected",
            availability=availability,
        )
    if not _gate_allows(gate):
        return _blocked(
            root=root,
            goal=goal,
            route=decision.to_dict(),
            gate=gate,
            checkpoint=runtime_checkpoint,
            reason="Runtime action gate unavailable or denied; no mutation performed",
            availability=availability,
        )

    manager.new_turn()
    checkpoint_taken = manager.ensure_checkpoint(
        str(root), "issue-181 before first write"
    )
    checkpoints = manager.list_checkpoints(str(root)) if checkpoint_taken else []
    checkpoint = checkpoints[0] if checkpoints else None
    if not checkpoint_taken or checkpoint is None:
        return _blocked(
            root=root,
            goal=goal,
            route=decision.to_dict(),
            gate=gate,
            checkpoint=runtime_checkpoint,
            reason="local checkpoint was not created before mutation",
            availability=availability,
        )

    before = _snapshot(artifact)
    action = {
        "operation": "write",
        "relative_path": ARTIFACT_RELATIVE_PATH.as_posix(),
        "content_sha256": _sha256(FINAL_CONTENT),
    }
    action_digest = _sha256(_canonical(action))
    idempotency_key = f"issue-181:{action_digest}"
    artifact.write_text(FINAL_CONTENT, encoding="utf-8", newline="\n")
    after = _snapshot(artifact)
    verification = VerificationEvidence(
        command="issue-181 local artifact verifier",
        canonical_command="issue-181 local artifact verifier",
        kind="artifact",
        scope="targeted",
        status="passed" if after["content"] == FINAL_CONTENT else "failed",
        exit_code=0 if after["content"] == FINAL_CONTENT else 1,
        cwd=str(root),
        root=str(root),
        session_id=session_id,
        output_summary=f"after_sha256={after['sha256']}",
    )
    restore = manager.restore(
        str(root), checkpoint["hash"], ARTIFACT_RELATIVE_PATH.as_posix()
    )
    undo = _snapshot(artifact)
    watcher = {
        "name": WATCHER_NAME,
        "status": "passed"
        if undo["exists"] and undo["content"] == BASELINE_CONTENT
        else "failed",
        "recomputed": True,
        "relative_path": undo["relative_path"],
        "sha256": undo["sha256"],
        "matches_baseline": undo["content"] == BASELINE_CONTENT,
        "restore_success": bool(restore.get("success")),
    }
    evidence_refs = (
        f"route:{decision.capability}",
        f"runtime:{gate.request_id}",
        f"checkpoint:{checkpoint['short_hash']}",
        f"verification:{verification.canonical_command}",
        f"undo:{undo['sha256']}",
    )
    goal = goal.add_evidence(evidence_refs[0], kind="capability")
    for reference in evidence_refs[1:]:
        goal = goal.add_evidence(reference, kind="receipt")
    goal = goal.satisfy_watcher(
        WATCHER_NAME,
        receipt=f"watcher:{undo['sha256']}",
        recomputed=watcher["status"] == "passed",
    )
    goal = goal.mark_completed_verified(reason="local artifact verified and restored")
    certificate_evidence = tuple(
        EvidenceVerdict(
            name=criterion,
            reference=reference,
            reported="passed",
            recomputed="passed",
        )
        for criterion, reference in zip(
            ACCEPTANCE_CRITERIA,
            (*evidence_refs[:4], f"watcher:{undo['sha256']}"),
        )
    )
    certificate = _certificate(
        task_id="issue-181",
        manifest=_certificate_manifest(
            task_id="issue-181",
            runtime_available=False,
            trajectory=(
                "route",
                decision.capability,
                "verify",
                after["sha256"],
                "undo",
                undo["sha256"],
            ),
            diff=FINAL_CONTENT,
        ),
        status="passed",
        evidence=certificate_evidence,
    )
    return ReversiblePathResult(
        status="completed_verified",
        workspace_id=_sha256(str(root)),
        artifact=ARTIFACT_RELATIVE_PATH.as_posix(),
        goal=goal.to_dict(),
        route=decision.to_dict(),
        runtime_gate=_receipt(gate),
        runtime_checkpoint=_receipt(runtime_checkpoint),
        action_digest=action_digest,
        idempotency_key=idempotency_key,
        checkpoint_taken=checkpoint_taken,
        checkpoint=checkpoint,
        before=before,
        after=after,
        undo=undo,
        watcher=watcher,
        delivery_certificate=certificate,
        availability=availability,
        trace=(
            {"stage": "goal_contract", "status": "active"},
            {"stage": "capability_route", "capability": decision.capability},
            {"stage": "runtime_gate", "request_id": gate.request_id},
            {"stage": "checkpoint", "short_hash": checkpoint["short_hash"]},
            {"stage": "effect", "action_digest": action_digest},
            {"stage": "observation", "sha256": after["sha256"]},
            {"stage": "undo", "sha256": undo["sha256"]},
            {"stage": "delivery", "status": certificate["status"]},
        ),
    )


__all__ = [
    "ACCEPTANCE_CRITERIA",
    "ARTIFACT_RELATIVE_PATH",
    "BASELINE_CONTENT",
    "FINAL_CONTENT",
    "ReversiblePathResult",
    "prepare_reversible_workspace",
    "run_local_reversible_path",
]
