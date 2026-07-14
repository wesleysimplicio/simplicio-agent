"""Read-only Agent consumer for the Runtime bootstrap transaction contract.

The Runtime owns bootstrap mutation and persistence.  This module only reads
the machine-readable ``status`` response so Agent diagnostics can report the
same transaction phase without parsing human output or opening Runtime state
files directly.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tools.runtime_manager import RuntimeStatus, repo_root, runtime_status


BOOTSTRAP_SCHEMA = "simplicio.bootstrap-transaction/v1"
BOOTSTRAP_PHASES = frozenset(
    {"fresh", "planned", "staging", "migrating", "verifying", "ready", "degraded", "rolling_back", "rolled_back", "failed"}
)


@dataclass(frozen=True)
class BootstrapTransactionStatus:
    """Sanitized status projection safe for Agent/doctor consumers."""

    phase: str | None
    transaction_id: str | None
    ready: bool
    checks: tuple[dict[str, Any], ...]
    receipt: dict[str, Any] | None
    reason_code: str
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": BOOTSTRAP_SCHEMA,
            "phase": self.phase,
            "transaction_id": self.transaction_id,
            "ready": self.ready,
            "checks": [dict(check) for check in self.checks],
            "receipt": dict(self.receipt) if self.receipt is not None else None,
            "reason_code": self.reason_code,
            "detail": self.detail,
        }


def read_bootstrap_transaction_status(
    *,
    runtime: RuntimeStatus | None = None,
    repo: Path | None = None,
    timeout: float = 10.0,
) -> BootstrapTransactionStatus:
    """Read Runtime bootstrap status without applying or repairing anything.

    The executable is selected through the existing verified Runtime status.
    A non-ready Runtime, malformed response, timeout, or non-zero command is
    represented as a typed diagnostic result rather than an exception.
    """

    runtime = runtime or runtime_status()
    if not runtime.satisfied or not runtime.bin_path:
        return BootstrapTransactionStatus(
            phase=None,
            transaction_id=None,
            ready=False,
            checks=(),
            receipt=None,
            reason_code="runtime_not_ready",
            detail="bootstrap transaction status requires a ready Runtime",
        )

    root = Path(repo) if repo is not None else repo_root()
    command = [runtime.bin_path, "bootstrap-transaction", "status", "--json"]
    try:
        completed = subprocess.run(
            command,
            cwd=str(root),
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return BootstrapTransactionStatus(
            phase=None,
            transaction_id=None,
            ready=False,
            checks=(),
            receipt=None,
            reason_code="runtime_bootstrap_status_unavailable",
            detail="Runtime bootstrap status command was unavailable",
        )

    if completed.returncode != 0:
        return BootstrapTransactionStatus(
            phase=None,
            transaction_id=None,
            ready=False,
            checks=(),
            receipt=None,
            reason_code="runtime_bootstrap_status_failed",
            detail="Runtime bootstrap status command failed",
        )

    try:
        payload = json.loads(completed.stdout)
    except (TypeError, json.JSONDecodeError):
        return BootstrapTransactionStatus(
            phase=None,
            transaction_id=None,
            ready=False,
            checks=(),
            receipt=None,
            reason_code="runtime_bootstrap_invalid_response",
            detail="Runtime returned non-JSON bootstrap status",
        )

    return _normalize_status(payload)


def _normalize_status(payload: object) -> BootstrapTransactionStatus:
    if not isinstance(payload, dict) or payload.get("schema") != BOOTSTRAP_SCHEMA:
        return BootstrapTransactionStatus(
            phase=None,
            transaction_id=None,
            ready=False,
            checks=(),
            receipt=None,
            reason_code="runtime_bootstrap_invalid_response",
            detail="Runtime bootstrap status schema is unsupported",
        )

    phase = payload.get("phase")
    transaction_id = payload.get("transaction_id")
    checks = payload.get("checks", [])
    receipt = payload.get("receipt")
    if (
        not isinstance(phase, str)
        or phase not in BOOTSTRAP_PHASES
        or (transaction_id is not None and not isinstance(transaction_id, str))
        or not isinstance(checks, list)
        or any(not isinstance(check, dict) for check in checks)
        or (receipt is not None and not isinstance(receipt, dict))
    ):
        return BootstrapTransactionStatus(
            phase=None,
            transaction_id=None,
            ready=False,
            checks=(),
            receipt=None,
            reason_code="runtime_bootstrap_invalid_response",
            detail="Runtime bootstrap status fields are invalid",
        )

    ready = phase == "ready" and receipt is not None
    reason_code = {
        "fresh": "bootstrap_not_started",
        "ready": "bootstrap_ready",
        "degraded": "bootstrap_degraded",
        "failed": "bootstrap_failed",
        "rolled_back": "bootstrap_rolled_back",
    }.get(phase, "bootstrap_in_progress")
    return BootstrapTransactionStatus(
        phase=phase,
        transaction_id=transaction_id,
        ready=ready,
        checks=tuple(dict(check) for check in checks),
        receipt=dict(receipt) if receipt is not None else None,
        reason_code=reason_code,
    )


__all__ = [
    "BOOTSTRAP_SCHEMA",
    "BootstrapTransactionStatus",
    "read_bootstrap_transaction_status",
]
