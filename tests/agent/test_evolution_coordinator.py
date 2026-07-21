from __future__ import annotations

from pathlib import Path

from agent.evolution_coordinator import (
    Evidence,
    EvolutionCoordinator,
    EvolutionLedger,
    EvolutionProposal,
    ProposalClass,
    ProposalState,
    ReceiptStatus,
    RemoteIssue,
)


def proposal(**changes: object) -> EvolutionProposal:
    values: dict[str, object] = {
        "run_id": "run-1",
        "task_id": "task-1",
        "stage_id": "stage-validate",
        "agent_id": "agent-1",
        "classification": ProposalClass.IMPROVEMENT,
        "component": "issue-reporting",
        "version": "v1",
        "owner": "wesleysimplicio/simplicio-agent",
        "limitation": "validated opportunities are not deduplicated before issue creation",
        "beneficiary": "maintainers reviewing continuous evolution findings",
        "evidence": (Evidence("test", "tests/agent/test_evolution_coordinator.py", "repeated proposal has one fingerprint"),),
        "expected_result": "one canonical remote issue per equivalent opportunity",
        "strategy": "add a deterministic contract at the existing Runtime handoff boundary",
        "rollback": "disable the invocation and retain the local ledger",
        "current_scope": "the active run only",
        "future_scope": "a separately approved backlog issue",
        "dimensions": {
            "impact": 0.8,
            "frequency": 0.6,
            "security": 0.2,
            "reliability": 0.8,
            "economy": 0.4,
            "unblock": 0.7,
            "effort": 0.3,
            "risk": 0.2,
            "confidence": 0.9,
        },
    }
    values.update(changes)
    return EvolutionProposal(**values)  # type: ignore[arg-type]


class FakeRuntime:
    def __init__(self, existing: RemoteIssue | None = None, confirm: bool = True) -> None:
        self.existing = existing
        self.confirm = confirm
        self.created = 0
        self.searched = 0

    def search_equivalent(self, *, owner: str, fingerprint: str):
        self.searched += 1
        return [self.existing] if self.existing else []

    def create_issue(self, *, owner: str, title: str, body: str, idempotency_key: str):
        self.created += 1
        self.existing = RemoteIssue("99", "https://github.com/wesleysimplicio/simplicio-agent/issues/99", title, idempotency_key.split(":", 1)[1])
        return self.existing

    def requery(self, *, owner: str, issue_id: str, fingerprint: str):
        return self.existing if self.confirm and self.existing and self.existing.issue_id == issue_id else None


def test_fingerprint_is_stable_and_public_text_is_redacted() -> None:
    first = proposal(limitation="token=top-secret validated limitation")
    second = proposal(limitation="token=another-secret validated limitation")

    assert first.fingerprint == second.fingerprint
    assert "top-secret" not in first.limitation
    assert "[REDACTED]" in first.limitation


def test_missing_evidence_is_unverified_and_never_calls_runtime() -> None:
    runtime = FakeRuntime()
    candidate = proposal(evidence=(Evidence("probe", "run://1", "not confirmed", ReceiptStatus.UNVERIFIED),))

    receipt = EvolutionCoordinator().open_issue(candidate, executor=runtime, approval=lambda _: True)

    assert receipt.status is ReceiptStatus.UNVERIFIED
    assert receipt.state is ProposalState.DEFERRED
    assert runtime.searched == 0
    assert runtime.created == 0


def test_approval_denial_is_fail_closed() -> None:
    runtime = FakeRuntime()

    receipt = EvolutionCoordinator().open_issue(proposal(), executor=runtime, approval=lambda _: False)

    assert receipt.status is ReceiptStatus.FAIL
    assert receipt.action == "approval_denied"
    assert runtime.created == 0


def test_equivalent_issue_is_linked_after_requery(tmp_path: Path) -> None:
    candidate = proposal()
    existing = RemoteIssue("41", "https://github.com/wesleysimplicio/simplicio-agent/issues/41", "canonical", candidate.fingerprint)
    runtime = FakeRuntime(existing=existing)
    coordinator = EvolutionCoordinator(EvolutionLedger(tmp_path / "ledger.sqlite"))

    receipt = coordinator.open_issue(candidate, executor=runtime, approval=lambda _: True)
    repeated = coordinator.open_issue(candidate, executor=runtime, approval=lambda _: True)

    assert receipt.status is ReceiptStatus.PASS
    assert repeated.status is ReceiptStatus.PASS
    assert receipt.action == "linked_existing"
    assert receipt.remote_confirmation is True
    assert runtime.created == 0
    assert coordinator.ledger.get(candidate.fingerprint)["occurrences"] == 2


def test_create_requires_remote_confirmation_and_records_pending() -> None:
    runtime = FakeRuntime(confirm=False)

    receipt = EvolutionCoordinator().open_issue(proposal(), executor=runtime, approval=lambda _: True)

    assert receipt.status is ReceiptStatus.UNVERIFIED
    assert receipt.state is ProposalState.ISSUE_REPORTING_PENDING
    assert receipt.action == "issue_reporting_pending"
    assert runtime.created == 1


def test_search_failure_does_not_create() -> None:
    class Broken(FakeRuntime):
        def search_equivalent(self, *, owner: str, fingerprint: str):
            raise TimeoutError

    runtime = Broken()
    receipt = EvolutionCoordinator().open_issue(proposal(), executor=runtime, approval=lambda _: True)

    assert receipt.status is ReceiptStatus.UNVERIFIED
    assert receipt.action == "search_failed"
    assert runtime.created == 0


def test_issue_budget_is_bounded() -> None:
    runtime = FakeRuntime()
    coordinator = EvolutionCoordinator(max_new_issues=0)

    receipt = coordinator.open_issue(proposal(), executor=runtime, approval=lambda _: True)

    assert receipt.status is ReceiptStatus.FAIL
    assert receipt.action == "budget_blocked"
    assert runtime.searched == 0
