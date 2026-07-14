"""Focused tests for the read-only Runtime bootstrap transaction consumer."""

import json
from types import SimpleNamespace
from unittest.mock import patch

import hermes_cli.doctor as doctor
from tools.bootstrap_transaction_client import (
    BOOTSTRAP_SCHEMA,
    read_bootstrap_transaction_status,
)


def _runtime(*, ready=True, binary="simplicio"):
    return SimpleNamespace(satisfied=ready, bin_path=binary)


def _completed(payload, *, returncode=0):
    return SimpleNamespace(returncode=returncode, stdout=json.dumps(payload), stderr="")


def test_runtime_not_ready_is_reported_without_spawning_process():
    with patch("tools.bootstrap_transaction_client.subprocess.run") as run:
        result = read_bootstrap_transaction_status(runtime=_runtime(ready=False))

    assert result.reason_code == "runtime_not_ready"
    run.assert_not_called()


def test_fresh_status_is_normalized_from_machine_readable_runtime_output():
    payload = {"schema": BOOTSTRAP_SCHEMA, "phase": "fresh"}
    with patch(
        "tools.bootstrap_transaction_client.subprocess.run",
        return_value=_completed(payload),
    ) as run:
        result = read_bootstrap_transaction_status(runtime=_runtime(), repo=".")

    assert result.to_dict() == {
        "schema": BOOTSTRAP_SCHEMA,
        "phase": "fresh",
        "transaction_id": None,
        "ready": False,
        "checks": [],
        "receipt": None,
        "reason_code": "bootstrap_not_started",
        "detail": "",
    }
    assert run.call_args.kwargs["cwd"] == "."
    assert run.call_args.args[0] == ["simplicio", "bootstrap-transaction", "status", "--json"]


def test_ready_status_preserves_only_structured_receipt_fields():
    payload = {
        "schema": BOOTSTRAP_SCHEMA,
        "transaction_id": "bootstrap-test",
        "phase": "ready",
        "checks": [{"name": "migration_boundary", "ok": True}],
        "receipt": {"kind": "bootstrap", "verified_at": 123, "idempotent": True},
        "repo": "must-not-be-forwarded",
    }
    with patch(
        "tools.bootstrap_transaction_client.subprocess.run",
        return_value=_completed(payload),
    ):
        result = read_bootstrap_transaction_status(runtime=_runtime())

    assert result.ready is True
    assert result.reason_code == "bootstrap_ready"
    assert result.to_dict()["receipt"] == payload["receipt"]
    assert "repo" not in result.to_dict()


def test_invalid_schema_and_command_failure_fail_closed():
    with patch(
        "tools.bootstrap_transaction_client.subprocess.run",
        return_value=_completed({"schema": "wrong", "phase": "ready"}),
    ):
        invalid = read_bootstrap_transaction_status(runtime=_runtime())
    assert invalid.reason_code == "runtime_bootstrap_invalid_response"

    with patch(
        "tools.bootstrap_transaction_client.subprocess.run",
        return_value=_completed({}, returncode=2),
    ):
        failed = read_bootstrap_transaction_status(runtime=_runtime())
    assert failed.reason_code == "runtime_bootstrap_status_failed"


def test_doctor_projects_ready_status_without_executing_a_mutation():
    status = SimpleNamespace(ready=True, transaction_id="bootstrap-test", reason_code="bootstrap_ready")
    with patch.object(doctor, "check_ok") as check_ok, patch.object(doctor, "check_info") as check_info, patch.object(doctor, "check_warn") as check_warn:
        doctor._report_bootstrap_transaction(status)

    check_ok.assert_called_once_with("bootstrap transaction ready", "(transaction bootstrap-test)")
    check_info.assert_not_called()
    check_warn.assert_not_called()
