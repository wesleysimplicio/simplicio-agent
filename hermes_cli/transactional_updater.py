"""Bounded transactional updater orchestration.

This module composes the local updater contracts without owning a live
installation.  It preserves a dirty checkout before staging, snapshots a
candidate through :class:`tools.transaction_primitives.UpdateTransaction`,
and records every state transition as a hash-chained receipt.  Restart and
live-code attestation are observation/callback boundaries: this module never
stops a process, starts a gateway, fetches a release, or publishes an
artifact.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from hermes_cli.local_change_staging import (
    ApplyResult,
    ChangeStore,
    Preservation,
    apply_preserved,
    inspect_dirty,
    preserve,
    verify_preserved,
)
from hermes_cli.staging_activation import (
    DetachedRestartHelper,
    DetachedRestartIntent,
    RestartResult,
)
from tools.live_commit_attestation import (
    AttestationResult,
    CodeIdentity,
    attest_live_commit,
    attest_rollback,
)
from tools.transaction_primitives import (
    SnapshotManifest,
    TransactionError,
    TransactionJournal,
    UpdateTransaction,
)


UPDATER_SCHEMA = "simplicio.transactional-update/v1"
MAX_PRESERVED_FILES = 10_000
MAX_PRESERVED_BYTES = 256 * 1024 * 1024


class TransactionalUpdateError(RuntimeError):
    """The bounded updater cannot safely continue."""


@dataclass(frozen=True)
class PreservationReceipt:
    """Receipt for the immutable dirty-tree capture."""

    manifest_digest: str
    patch_digest: str
    base_commit: str
    paths: tuple[str, ...]
    verified: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "paths", tuple(sorted(set(self.paths))))

    def to_dict(self) -> dict[str, object]:
        return {
            "manifest_digest": self.manifest_digest,
            "patch_digest": self.patch_digest,
            "base_commit": self.base_commit,
            "paths": list(self.paths),
            "verified": self.verified,
        }


@dataclass(frozen=True)
class UpdateReceipt:
    """Stable evidence for one updater boundary."""

    operation: str
    status: str
    before: str | None = None
    after: str | None = None
    preserved: tuple[str, ...] = ()
    rollback_required: bool = False
    reason: str = ""
    detail: Mapping[str, object] | None = None

    def __post_init__(self) -> None:
        if not self.operation or "\n" in self.operation:
            raise ValueError("receipt operation must be a single non-empty line")
        if not self.status or "\n" in self.status:
            raise ValueError("receipt status must be a single non-empty line")
        object.__setattr__(self, "preserved", tuple(sorted(set(self.preserved))))
        if self.detail is not None:
            object.__setattr__(
                self, "detail", json.loads(json.dumps(self.detail, sort_keys=True))
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": UPDATER_SCHEMA,
            "operation": self.operation,
            "status": self.status,
            "before": self.before,
            "after": self.after,
            "preserved": list(self.preserved),
            "rollback_required": self.rollback_required,
            "reason": self.reason,
            "detail": self.detail,
        }

    def digest(self) -> str:
        payload = json.dumps(
            self.to_dict(), sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class StagedCandidate:
    """A content-addressed candidate and its optional preserved changes."""

    manifest: SnapshotManifest
    preservation: PreservationReceipt | None = None


class TransactionalUpdater:
    """Compose bounded update primitives under an explicitly supplied root.

    ``root`` is a disposable state directory containing snapshots, the atomic
    pointer, and the receipt journal.  It is intentionally independent from
    the checkout being preserved and from any live gateway installation.
    """

    def __init__(
        self,
        root: Path,
        *,
        max_preserved_files: int = MAX_PRESERVED_FILES,
        max_preserved_bytes: int = MAX_PRESERVED_BYTES,
    ) -> None:
        if max_preserved_files <= 0 or max_preserved_bytes <= 0:
            raise ValueError("preservation bounds must be positive")
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.transaction = UpdateTransaction(self.root)
        self.change_store = ChangeStore(self.root / "local-changes")
        self.receipt_journal = TransactionJournal(self.root / "receipts.jsonl")
        self.max_preserved_files = max_preserved_files
        self.max_preserved_bytes = max_preserved_bytes

    def current(self):
        """Return the validated atomic pointer, if one has been published."""

        return self.transaction.current()

    def preserve_dirty_tree(
        self, checkout: Path
    ) -> tuple[Preservation, PreservationReceipt]:
        """Capture dirty tracked/untracked files before staging or fetch work."""

        checkout = Path(checkout).expanduser().resolve()
        dirty = inspect_dirty(checkout)
        if len(dirty.files) > self.max_preserved_files:
            raise TransactionalUpdateError("dirty tree contains too many paths")
        dirty_bytes = sum(item.size_bytes for item in dirty.files)
        if dirty_bytes > self.max_preserved_bytes:
            raise TransactionalUpdateError(
                f"dirty tree exceeds {self.max_preserved_bytes} bytes"
            )
        preservation = preserve(checkout, self.change_store)
        if not verify_preserved(preservation, self.change_store):
            raise TransactionalUpdateError(
                "dirty-tree preservation failed verification"
            )
        patch = self.change_store.get(preservation.patch_digest)
        if len(patch) > self.max_preserved_bytes:
            raise TransactionalUpdateError("preserved patch exceeds byte bound")
        receipt = PreservationReceipt(
            preservation.manifest_digest,
            preservation.patch_digest,
            preservation.manifest.base_commit,
            tuple(entry.path for entry in preservation.manifest.files),
            True,
        )
        self._record(
            UpdateReceipt(
                "preserve",
                "verified",
                after=receipt.manifest_digest,
                preserved=receipt.paths,
                detail=receipt.to_dict(),
            )
        )
        return preservation, receipt

    # Short alias for callers that use the lower-level contract's name.
    preserve = preserve_dirty_tree

    def stage(
        self,
        source: Path,
        *,
        preservation: Preservation | None = None,
    ) -> StagedCandidate:
        """Snapshot a candidate, optionally applying preserved files in a copy."""

        source = Path(source).expanduser().resolve()
        source_for_snapshot = source
        preserved_receipt: PreservationReceipt | None = None
        with tempfile.TemporaryDirectory(prefix="simplicio-update-") as temporary:
            if preservation is not None:
                copied = Path(temporary) / "candidate"
                shutil.copytree(source, copied, symlinks=False)
                applied: ApplyResult = apply_preserved(
                    copied, preservation, self.change_store
                )
                if applied.status != "applied":
                    raise TransactionalUpdateError(
                        "preserved changes conflict in staging: "
                        + ", ".join(applied.conflicts)
                    )
                source_for_snapshot = copied
                preserved_receipt = PreservationReceipt(
                    preservation.manifest_digest,
                    preservation.patch_digest,
                    preservation.manifest.base_commit,
                    tuple(entry.path for entry in preservation.manifest.files),
                    verify_preserved(preservation, self.change_store),
                )
            try:
                manifest = self.transaction.stage(source_for_snapshot)
            except (OSError, TransactionError) as exc:
                self._record(
                    UpdateReceipt(
                        "stage",
                        "failed",
                        reason=str(exc),
                        preserved=preserved_receipt.paths if preserved_receipt else (),
                    )
                )
                raise TransactionalUpdateError(
                    f"candidate staging failed: {exc}"
                ) from exc
        self._record(
            UpdateReceipt(
                "stage",
                "staged",
                after=manifest.snapshot_id,
                preserved=preserved_receipt.paths if preserved_receipt else (),
                detail={
                    "snapshot": manifest.to_dict(),
                    "preservation": preserved_receipt.to_dict()
                    if preserved_receipt
                    else None,
                },
            )
        )
        return StagedCandidate(manifest, preserved_receipt)

    def activate(
        self,
        candidate: StagedCandidate | SnapshotManifest,
        *,
        health_check: Callable[[SnapshotManifest], bool] | None = None,
    ) -> UpdateReceipt:
        """Atomically publish a candidate while retaining the prior pointer."""

        manifest = (
            candidate.manifest if isinstance(candidate, StagedCandidate) else candidate
        )
        before = self.current()
        try:
            pointer = self.transaction.activate(manifest, health_check=health_check)
        except TransactionError as exc:
            self._record(
                UpdateReceipt(
                    "activate",
                    "rolled_back",
                    before.current if before else None,
                    before.current if before else None,
                    candidate.preservation.paths
                    if isinstance(candidate, StagedCandidate) and candidate.preservation
                    else (),
                    reason=str(exc),
                )
            )
            raise TransactionalUpdateError(str(exc)) from exc
        receipt = UpdateReceipt(
            "activate",
            "committed",
            before.current if before else None,
            pointer.current,
            candidate.preservation.paths
            if isinstance(candidate, StagedCandidate) and candidate.preservation
            else (),
            detail={"previous": pointer.previous},
        )
        self._record(receipt)
        return receipt

    def rollback(self) -> UpdateReceipt:
        """Atomically restore the previous snapshot and emit evidence."""

        before = self.current()
        try:
            pointer = self.transaction.rollback()
        except TransactionError as exc:
            self._record(
                UpdateReceipt(
                    "rollback",
                    "failed",
                    before.current if before else None,
                    reason=str(exc),
                )
            )
            raise TransactionalUpdateError(str(exc)) from exc
        receipt = UpdateReceipt(
            "rollback",
            "rolled_back",
            before.current if before else None,
            pointer.current,
            rollback_required=False,
            detail={"previous": pointer.previous},
        )
        self._record(receipt)
        return receipt

    def recover(self) -> Any:
        """Re-read the durable pointer after a stop/kill during an update."""

        pointer = self.transaction.current()
        self._record(
            UpdateReceipt(
                "recover",
                "reconciled",
                pointer.current if pointer else None,
                pointer.current if pointer else None,
                reason="durable pointer reconciled after restart",
            )
        )
        return pointer

    def restart(
        self,
        intent: DetachedRestartIntent,
        *,
        wait_for_drain: Callable[[float], bool],
        request_supervisor_restart: Callable[[DetachedRestartIntent], bool],
        wait_for_startup: Callable[[DetachedRestartIntent, float], bool],
    ) -> RestartResult:
        """Run the detached restart protocol and record its result only."""

        result = DetachedRestartHelper(intent).run(
            wait_for_drain=wait_for_drain,
            request_supervisor_restart=request_supervisor_restart,
            wait_for_startup=wait_for_startup,
        )
        self._record(
            UpdateReceipt(
                "restart",
                result.phase.value,
                reason=result.detail,
                detail={"intent": intent.to_dict()},
            )
        )
        return result

    def attest(
        self,
        expected: CodeIdentity,
        observed: CodeIdentity | None,
        *,
        startup_ok: bool = True,
        health_ok: bool = True,
        rollback_target: CodeIdentity | None = None,
    ) -> AttestationResult:
        """Record live-code attestation; failed probes request rollback."""

        result = attest_live_commit(
            expected,
            observed,
            startup_ok=startup_ok,
            health_ok=health_ok,
            rollback_target=rollback_target,
        )
        self._record(
            UpdateReceipt(
                "attest",
                result.status.value,
                rollback_required=result.rollback_required,
                reason=result.reason,
                detail=result.to_dict(),
            )
        )
        return result

    def attest_rollback(
        self,
        expected_previous: CodeIdentity,
        observed: CodeIdentity | None,
        *,
        startup_ok: bool = True,
        health_ok: bool = True,
    ) -> AttestationResult:
        """Record verification of the old live identity after rollback."""

        result = attest_rollback(
            expected_previous,
            observed,
            startup_ok=startup_ok,
            health_ok=health_ok,
        )
        self._record(
            UpdateReceipt(
                "attest_rollback",
                result.status.value,
                rollback_required=result.rollback_required,
                reason=result.reason,
                detail=result.to_dict(),
            )
        )
        return result

    def receipts(self) -> tuple[dict[str, object], ...]:
        """Return validated receipt payloads from the durable journal."""

        return tuple(record.payload for record in self.receipt_journal.records())

    def _record(self, receipt: UpdateReceipt) -> None:
        self.receipt_journal.append(
            "receipt",
            {**receipt.to_dict(), "receipt_digest": receipt.digest()},
        )


__all__ = [
    "MAX_PRESERVED_BYTES",
    "MAX_PRESERVED_FILES",
    "PreservationReceipt",
    "StagedCandidate",
    "TransactionalUpdateError",
    "TransactionalUpdater",
    "UPDATER_SCHEMA",
    "UpdateReceipt",
]
