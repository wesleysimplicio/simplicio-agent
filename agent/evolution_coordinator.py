"""Evidence-gated discovery and issue handoff for continuous evolution.

This module is an invocation-time contract, not a scheduler or a second
coordinator.  It keeps the reasoning side deterministic and delegates every
remote mutation to a Runtime-owned executor supplied by the caller.

The external executor must search before create, and must re-query after every
mutation.  A missing search, approval, owner, provenance, or confirmation is
reported as ``UNVERIFIED``/``FAIL`` and never becomes an issue-opening side
effect.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Sequence


PROPOSAL_SCHEMA = "simplicio.evolution-proposal/v1"
RECEIPT_SCHEMA = "simplicio.evolution-receipt/v1"
MARKER_PREFIX = "<!-- simplicio-evolution:fingerprint="
_SECRET_PATTERNS = (
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+"),
    re.compile(r"(?i)(gh[pousr]_)[A-Za-z0-9_]+"),
    re.compile(r"(?i)(api[_-]?key|token|secret|password)(\s*[:=]\s*)[^\s,;]+"),
)
_REQUIRED_DIMENSIONS = (
    "impact",
    "frequency",
    "security",
    "reliability",
    "economy",
    "unblock",
    "effort",
    "risk",
    "confidence",
)
_WEIGHTS = {
    "impact": 2.0,
    "frequency": 1.0,
    "security": 2.0,
    "reliability": 2.0,
    "economy": 1.0,
    "unblock": 1.0,
    "effort": -1.0,
    "risk": -1.0,
    "confidence": 1.0,
}


class ProposalClass(str, Enum):
    DEFECT = "defect"
    REGRESSION = "regression"
    IMPROVEMENT = "improvement"
    EVOLUTION = "evolution"
    OPTIMIZATION = "optimization"
    HARDENING = "hardening"
    DISCOVERY = "discovery"
    MAINTENANCE = "maintenance"


class ProposalState(str, Enum):
    OBSERVED = "observed"
    VALIDATED = "validated"
    LINKED = "linked"
    ISSUE_CREATED = "issue-created"
    ISSUE_REPORTING_PENDING = "issue_reporting_pending"
    DEFERRED = "deferred"
    REJECTED = "rejected"


class ReceiptStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNVERIFIED = "UNVERIFIED"


def _text(value: Any, field: str) -> str:
    value = str(value or "").strip()
    if not value:
        raise ValueError(f"{field} must be non-empty")
    return value


def _public(value: Any) -> str:
    """Return bounded public text with obvious credentials redacted."""

    result = " ".join(str(value or "").split())
    for pattern in _SECRET_PATTERNS:
        result = pattern.sub(lambda match: f"{match.group(1)}[REDACTED]", result)
    return result[:4000]


@dataclass(frozen=True, slots=True)
class Evidence:
    kind: str
    ref: str
    summary: str
    status: ReceiptStatus = ReceiptStatus.PASS

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", _text(self.kind, "evidence.kind"))
        object.__setattr__(self, "ref", _public(_text(self.ref, "evidence.ref")))
        object.__setattr__(self, "summary", _public(_text(self.summary, "evidence.summary")))
        if not isinstance(self.status, ReceiptStatus):
            object.__setattr__(self, "status", ReceiptStatus(str(self.status)))

    def to_dict(self) -> dict[str, str]:
        return {
            "kind": self.kind,
            "ref": self.ref,
            "summary": self.summary,
            "status": self.status.value,
        }


@dataclass(frozen=True, slots=True)
class EvolutionProposal:
    run_id: str
    task_id: str
    stage_id: str
    agent_id: str
    classification: ProposalClass
    component: str
    version: str
    owner: str
    limitation: str
    beneficiary: str
    evidence: tuple[Evidence, ...]
    expected_result: str
    strategy: str
    rollback: str
    current_scope: str
    future_scope: str
    dimensions: Mapping[str, float]
    baseline: str | None = None
    dependencies: tuple[str, ...] = ()
    alternatives: tuple[str, ...] = ()
    compatibility: str = ""

    def __post_init__(self) -> None:
        for field in (
            "run_id",
            "task_id",
            "stage_id",
            "agent_id",
            "component",
            "version",
            "owner",
            "limitation",
            "beneficiary",
            "expected_result",
            "strategy",
            "rollback",
            "current_scope",
            "future_scope",
        ):
            object.__setattr__(self, field, _public(_text(getattr(self, field), field)))
        if not isinstance(self.classification, ProposalClass):
            object.__setattr__(self, "classification", ProposalClass(str(self.classification)))
        if not self.evidence:
            raise ValueError("evidence must contain at least one item")
        object.__setattr__(self, "evidence", tuple(self.evidence))
        object.__setattr__(self, "baseline", _public(self.baseline) if self.baseline else None)
        object.__setattr__(self, "dependencies", tuple(_public(item) for item in self.dependencies))
        object.__setattr__(self, "alternatives", tuple(_public(item) for item in self.alternatives))
        object.__setattr__(self, "compatibility", _public(self.compatibility))
        dimensions = {str(key): float(value) for key, value in dict(self.dimensions).items()}
        for key, value in dimensions.items():
            if not math.isfinite(value) or not 0.0 <= value <= 1.0:
                raise ValueError(f"dimension {key} must be finite and between 0 and 1")
        object.__setattr__(self, "dimensions", dimensions)

    @property
    def fingerprint(self) -> str:
        identity = {
            "classification": self.classification.value,
            "component": self.component,
            "owner": self.owner,
            "limitation": self.limitation,
            "expected_result": self.expected_result,
            "future_scope": self.future_scope,
        }
        canonical = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]

    @property
    def idempotency_key(self) -> str:
        return f"evolution:{self.fingerprint}"

    def provenance(self) -> dict[str, str]:
        return {
            "run_id": self.run_id,
            "task_id": self.task_id,
            "stage_id": self.stage_id,
            "agent_id": self.agent_id,
        }

    def priority(self) -> tuple[float | None, ReceiptStatus, str]:
        missing = [name for name in _REQUIRED_DIMENSIONS if name not in self.dimensions]
        if missing:
            return None, ReceiptStatus.UNVERIFIED, "missing dimensions: " + ", ".join(missing)
        score = sum(_WEIGHTS[name] * self.dimensions[name] for name in _REQUIRED_DIMENSIONS)
        formula = " + ".join(
            f"{_WEIGHTS[name]:g}*{name}" for name in _REQUIRED_DIMENSIONS
        )
        return round(score, 6), ReceiptStatus.PASS, formula

    def issue_body(self, priority_score: float) -> str:
        evidence = "\n".join(
            f"- `{item.kind}` — {item.summary} ([{item.status.value}] {item.ref})"
            for item in self.evidence
        )
        dimensions = ", ".join(
            f"{name}={self.dimensions[name]:g}" for name in _REQUIRED_DIMENSIONS
        )
        return f"""{MARKER_PREFIX}{self.fingerprint} -->
## Origin and provenance
- run/task/stage/agent: `{self.run_id}` / `{self.task_id}` / `{self.stage_id}` / `{self.agent_id}`
- owner: `{self.owner}`
- idempotency key: `{self.idempotency_key}`

## Current state and evidence
**Limitation:** {self.limitation}

**Beneficiary/flow:** {self.beneficiary}

{evidence}

**Baseline:** {self.baseline or "not applicable; no metric is claimed"}

## Desired result and impact
{self.expected_result}

- classification: `{self.classification.value}`
- priority score: `{priority_score:g}` (formula inputs: {dimensions})
- current execution scope: {self.current_scope}
- future backlog scope: {self.future_scope}

## Scope and implementation plan
- in scope: {self.future_scope}
- out of current run scope: {self.current_scope}
- strategy: {self.strategy}
- dependencies: {", ".join(self.dependencies) or "none recorded"}
- alternatives: {", ".join(self.alternatives) or "none recorded"}
- compatibility: {self.compatibility or "UNVERIFIED"}

## Tests, compatibility, risks and rollback
- tests: add unit, integration, system, security and performance checks applicable to the change
- risk/blast radius: bounded by the owner/component above; validate before rollout
- rollback: {self.rollback}

## Acceptance criteria and Definition of Done
- [ ] Evidence and baseline are reproducible and linked to receipts.
- [ ] The contract is covered by focused tests and remote confirmation.
- [ ] The implementation remains outside the current run working set.
- [ ] Rollback and compatibility behavior are verified.
"""


@dataclass(frozen=True, slots=True)
class RemoteIssue:
    issue_id: str
    url: str
    title: str
    fingerprint: str


class RuntimeIssueExecutor(Protocol):
    """Runtime-owned seam for read/search and approved remote mutations."""

    def search_equivalent(self, *, owner: str, fingerprint: str) -> Sequence[RemoteIssue]: ...

    def create_issue(self, *, owner: str, title: str, body: str, idempotency_key: str) -> RemoteIssue: ...

    def requery(self, *, owner: str, issue_id: str, fingerprint: str) -> RemoteIssue | None: ...


@dataclass(frozen=True, slots=True)
class EvolutionReceipt:
    status: ReceiptStatus
    action: str
    state: ProposalState
    fingerprint: str
    idempotency_key: str
    provenance: Mapping[str, str]
    reasons: tuple[str, ...] = ()
    remote_confirmation: bool = False
    issue_url: str | None = None
    priority_score: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": RECEIPT_SCHEMA,
            "status": self.status.value,
            "action": self.action,
            "state": self.state.value,
            "fingerprint": self.fingerprint,
            "idempotency_key": self.idempotency_key,
            "provenance": dict(self.provenance),
            "reasons": list(self.reasons),
            "remote_confirmation": self.remote_confirmation,
            "issue_url": self.issue_url,
            "priority_score": self.priority_score,
        }


class EvolutionLedger:
    """Durable local memory for fingerprints, occurrences and remote links."""

    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        self._connection = sqlite3.connect(self.path)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS evolution_ledger (
                fingerprint TEXT PRIMARY KEY,
                state TEXT NOT NULL,
                occurrences INTEGER NOT NULL,
                issue_id TEXT,
                issue_url TEXT,
                provenance TEXT NOT NULL,
                receipt TEXT
            )
            """
        )
        self._connection.commit()

    def get(self, fingerprint: str) -> sqlite3.Row | None:
        return self._connection.execute(
            "SELECT * FROM evolution_ledger WHERE fingerprint = ?", (fingerprint,)
        ).fetchone()

    def observe(self, proposal: EvolutionProposal, state: ProposalState) -> None:
        current = self.get(proposal.fingerprint)
        if current:
            provenance = json.loads(current["provenance"])
            provenance.update(proposal.provenance())
            self._connection.execute(
                "UPDATE evolution_ledger SET occurrences = occurrences + 1, provenance = ?, state = ? WHERE fingerprint = ?",
                (json.dumps(provenance, sort_keys=True), state.value, proposal.fingerprint),
            )
        else:
            self._connection.execute(
                "INSERT INTO evolution_ledger(fingerprint,state,occurrences,provenance) VALUES(?,?,?,?)",
                (proposal.fingerprint, state.value, 1, json.dumps(proposal.provenance(), sort_keys=True)),
            )
        self._connection.commit()

    def record_remote(self, proposal: EvolutionProposal, state: ProposalState, remote: RemoteIssue, receipt: EvolutionReceipt) -> None:
        self._connection.execute(
            """
            INSERT INTO evolution_ledger(fingerprint,state,occurrences,issue_id,issue_url,provenance,receipt)
            VALUES(?,?,?,?,?,?,?)
            ON CONFLICT(fingerprint) DO UPDATE SET state=excluded.state, issue_id=excluded.issue_id,
              issue_url=excluded.issue_url, provenance=excluded.provenance, receipt=excluded.receipt
            """,
            (
                proposal.fingerprint,
                state.value,
                max(1, int((self.get(proposal.fingerprint) or {"occurrences": 1})["occurrences"])),
                remote.issue_id,
                remote.url,
                json.dumps(proposal.provenance(), sort_keys=True),
                json.dumps(receipt.to_dict(), sort_keys=True),
            ),
        )
        self._connection.commit()


Approval = Callable[[Mapping[str, Any]], bool]


class EvolutionCoordinator:
    """One bounded proposal decision; the caller owns when it is invoked."""

    def __init__(self, ledger: EvolutionLedger | None = None, *, max_new_issues: int = 1) -> None:
        if not isinstance(max_new_issues, int) or max_new_issues < 0:
            raise ValueError("max_new_issues must be a non-negative integer")
        self.ledger = ledger or EvolutionLedger()
        self.max_new_issues = max_new_issues
        self._created = 0

    @staticmethod
    def _receipt(proposal: EvolutionProposal, status: ReceiptStatus, action: str, state: ProposalState, *, reasons: Sequence[str] = (), remote_confirmation: bool = False, issue_url: str | None = None, priority_score: float | None = None) -> EvolutionReceipt:
        return EvolutionReceipt(status, action, state, proposal.fingerprint, proposal.idempotency_key, proposal.provenance(), tuple(reasons), remote_confirmation, issue_url, priority_score)

    def _validate(self, proposal: EvolutionProposal) -> tuple[ReceiptStatus, tuple[str, ...], float | None]:
        reasons: list[str] = []
        if proposal.classification is ProposalClass.DISCOVERY:
            reasons.append("discovery is not sufficiently proven for issue opening")
        if proposal.current_scope == proposal.future_scope:
            reasons.append("current and future scope must be distinct")
        if proposal.classification is ProposalClass.OPTIMIZATION and not proposal.baseline:
            reasons.append("optimization requires a baseline")
        for item in proposal.evidence:
            if item.status is ReceiptStatus.FAIL:
                reasons.append(f"evidence failed: {item.kind}")
            elif item.status is ReceiptStatus.UNVERIFIED:
                reasons.append(f"evidence unverified: {item.kind}")
        score, score_status, formula = proposal.priority()
        if score_status is not ReceiptStatus.PASS:
            reasons.append(formula)
        if reasons:
            status = ReceiptStatus.UNVERIFIED if any("unverified" in reason or "baseline" in reason or "discovery" in reason or "dimensions" in reason for reason in reasons) else ReceiptStatus.FAIL
            return status, tuple(reasons), score
        return ReceiptStatus.PASS, (f"priority formula: {formula}",), score

    def open_issue(self, proposal: EvolutionProposal, *, executor: RuntimeIssueExecutor, approval: Approval) -> EvolutionReceipt:
        validation, reasons, score = self._validate(proposal)
        self.ledger.observe(proposal, ProposalState.OBSERVED)
        if validation is not ReceiptStatus.PASS:
            state = ProposalState.DEFERRED if validation is ReceiptStatus.UNVERIFIED else ProposalState.REJECTED
            receipt = self._receipt(proposal, validation, "no_mutation", state, reasons=reasons, priority_score=score)
            self.ledger.observe(proposal, state)
            return receipt
        if self._created >= self.max_new_issues:
            receipt = self._receipt(proposal, ReceiptStatus.FAIL, "budget_blocked", ProposalState.DEFERRED, reasons=("issue budget exhausted",), priority_score=score)
            self.ledger.observe(proposal, ProposalState.DEFERRED)
            return receipt
        try:
            matches = tuple(executor.search_equivalent(owner=proposal.owner, fingerprint=proposal.fingerprint))
        except Exception as exc:
            receipt = self._receipt(proposal, ReceiptStatus.UNVERIFIED, "search_failed", ProposalState.VALIDATED, reasons=(f"dedupe search unavailable: {type(exc).__name__}",), priority_score=score)
            self.ledger.observe(proposal, ProposalState.VALIDATED)
            return receipt
        if len(matches) > 1:
            receipt = self._receipt(proposal, ReceiptStatus.UNVERIFIED, "ambiguous_duplicate", ProposalState.VALIDATED, reasons=("multiple equivalent remote issues returned",), priority_score=score)
            self.ledger.observe(proposal, ProposalState.VALIDATED)
            return receipt
        if matches:
            remote = matches[0]
            try:
                confirmed = executor.requery(owner=proposal.owner, issue_id=remote.issue_id, fingerprint=proposal.fingerprint)
            except Exception:
                confirmed = None
            if confirmed is None:
                receipt = self._receipt(proposal, ReceiptStatus.UNVERIFIED, "requery_failed", ProposalState.ISSUE_REPORTING_PENDING, reasons=("existing issue could not be remotely confirmed",), priority_score=score)
                self.ledger.observe(proposal, ProposalState.ISSUE_REPORTING_PENDING)
                return receipt
            receipt = self._receipt(proposal, ReceiptStatus.PASS, "linked_existing", ProposalState.LINKED, remote_confirmation=True, issue_url=confirmed.url, priority_score=score)
            self.ledger.record_remote(proposal, ProposalState.LINKED, confirmed, receipt)
            return receipt
        action = {"operation": "create_issue", "owner": proposal.owner, "fingerprint": proposal.fingerprint, "idempotency_key": proposal.idempotency_key}
        try:
            approved = bool(approval(action))
        except Exception:
            approved = False
        if not approved:
            receipt = self._receipt(proposal, ReceiptStatus.FAIL, "approval_denied", ProposalState.REJECTED, reasons=("Runtime/action-gate approval was not granted",), priority_score=score)
            self.ledger.observe(proposal, ProposalState.REJECTED)
            return receipt
        try:
            remote = executor.create_issue(owner=proposal.owner, title=f"[{proposal.classification.value}] {proposal.limitation}", body=proposal.issue_body(score or 0.0), idempotency_key=proposal.idempotency_key)
            confirmed = executor.requery(owner=proposal.owner, issue_id=remote.issue_id, fingerprint=proposal.fingerprint)
        except Exception as exc:
            receipt = self._receipt(proposal, ReceiptStatus.UNVERIFIED, "issue_reporting_pending", ProposalState.ISSUE_REPORTING_PENDING, reasons=(f"remote mutation confirmation unavailable: {type(exc).__name__}",), priority_score=score)
            self.ledger.observe(proposal, ProposalState.ISSUE_REPORTING_PENDING)
            return receipt
        if confirmed is None:
            receipt = self._receipt(proposal, ReceiptStatus.UNVERIFIED, "issue_reporting_pending", ProposalState.ISSUE_REPORTING_PENDING, reasons=("issue creation was not confirmed by re-query",), priority_score=score)
            self.ledger.observe(proposal, ProposalState.ISSUE_REPORTING_PENDING)
            return receipt
        self._created += 1
        receipt = self._receipt(proposal, ReceiptStatus.PASS, "issue_created", ProposalState.ISSUE_CREATED, remote_confirmation=True, issue_url=confirmed.url, priority_score=score)
        self.ledger.record_remote(proposal, ProposalState.ISSUE_CREATED, confirmed, receipt)
        return receipt


__all__ = [
    "Approval",
    "Evidence",
    "EvolutionCoordinator",
    "EvolutionLedger",
    "EvolutionProposal",
    "EvolutionReceipt",
    "MARKER_PREFIX",
    "ProposalClass",
    "ProposalState",
    "ReceiptStatus",
    "RemoteIssue",
    "RuntimeIssueExecutor",
]
