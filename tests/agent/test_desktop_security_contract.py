"""Focused invariants for the bounded Desktop security/privacy contract."""

from __future__ import annotations

from agent.desktop_security_contract import (
    MAX_RETENTION_SECONDS,
    AuthorizationDecision,
    DesktopActionRequest,
    DesktopSecurityContract,
    Permission,
    PermissionPolicy,
    RedactionPolicy,
    RetentionPolicy,
    RiskApproval,
    RiskLevel,
    SecretBackend,
    SecretHandlingPolicy,
    SecretReference,
    TelemetryMode,
    TelemetryPolicy,
    ViolationCode,
)


def _safe_contract(**overrides: object) -> DesktopSecurityContract:
    values: dict[str, object] = {
        "permissions": PermissionPolicy(frozenset({Permission.READ_WORKSPACE})),
    }
    values.update(overrides)
    return DesktopSecurityContract(**values)


def test_defaults_are_private_and_safe_but_deny_capabilities_by_default() -> None:
    contract = DesktopSecurityContract()

    assert contract.is_safe
    assert contract.telemetry.mode is TelemetryMode.OFF
    assert not contract.telemetry.external_enabled
    assert not contract.permissions.allows(Permission.READ_WORKSPACE)
    assert contract.to_dict()["schema_version"].endswith("/v1")


def test_secret_policy_requires_reference_and_never_serializes_secret_material() -> None:
    contract = _safe_contract()
    request = DesktopActionRequest(
        action="read-provider-secret",
        scope="profile:default",
        permissions=frozenset({Permission.READ_WORKSPACE}),
        secret_required=True,
    )

    decision = contract.authorize(request, now=100.0)

    assert not decision.allowed
    assert any(v.code is ViolationCode.SECRET_REFERENCE_REQUIRED for v in decision.violations)
    reference = SecretReference("provider/openai")
    assert reference.to_dict() == {"name": "provider/openai", "backend": "native_vault"}
    assert "canary-secret" not in str(contract.to_dict())


def test_unsafe_secret_settings_fail_closed() -> None:
    contract = DesktopSecurityContract(
        secret_handling=SecretHandlingPolicy(
            backend=SecretBackend.CONSENTED_FALLBACK,
            fallback_consent=False,
            allow_plaintext=True,
        ),
        permissions=PermissionPolicy(frozenset({Permission.READ_WORKSPACE})),
    )

    assert not contract.is_safe
    decision = contract.authorize(
        DesktopActionRequest(
            action="read-file",
            scope="workspace:a",
            permissions=frozenset({Permission.READ_WORKSPACE}),
        ),
        now=100.0,
    )
    assert not decision.allowed
    assert any(v.code is ViolationCode.UNSAFE_SECRET_POLICY for v in decision.violations)


def test_secret_reference_must_use_the_configured_backend() -> None:
    contract = _safe_contract(
        secret_handling=SecretHandlingPolicy(
            backend=SecretBackend.CONSENTED_FALLBACK,
            fallback_consent=True,
        )
    )
    request = DesktopActionRequest(
        action="use-secret",
        scope="profile:default",
        permissions=frozenset({Permission.READ_WORKSPACE}),
        secret_required=True,
        secret_reference=SecretReference("provider/key"),
    )

    decision = contract.authorize(request, now=100.0)

    assert not decision.allowed
    assert any(v.code is ViolationCode.UNSAFE_SECRET_POLICY for v in decision.violations)


def test_permissions_are_an_explicit_allowlist() -> None:
    contract = _safe_contract()
    denied = contract.authorize(
        DesktopActionRequest(
            action="write-file",
            scope="workspace:a",
            permissions=frozenset({Permission.WRITE_WORKSPACE}),
        ),
        now=100.0,
    )
    allowed = contract.authorize(
        DesktopActionRequest(
            action="read-file",
            scope="workspace:a",
            permissions=frozenset({Permission.READ_WORKSPACE}),
        ),
        now=100.0,
    )

    assert not denied.allowed
    assert any(v.code is ViolationCode.PERMISSION_NOT_GRANTED for v in denied.violations)
    assert allowed == AuthorizationDecision(True)


def test_telemetry_is_off_until_explicitly_consented_and_metadata_only() -> None:
    no_consent = _safe_contract(
        telemetry=TelemetryPolicy(
            mode=TelemetryMode.OPT_IN,
            destination="https://telemetry.invalid",
            fields=frozenset({"status"}),
        )
    )
    assert not no_consent.is_safe
    assert not no_consent.telemetry.external_enabled

    enabled = _safe_contract(
        telemetry=TelemetryPolicy(
            mode=TelemetryMode.OPT_IN,
            consent=True,
            destination="https://telemetry.invalid",
            fields=frozenset({"status", "duration_ms"}),
        )
    )
    assert enabled.is_safe
    assert enabled.telemetry.external_enabled
    decision = enabled.authorize(
        DesktopActionRequest(
            action="send-metric",
            scope="profile:default",
            permissions=frozenset({Permission.READ_WORKSPACE}),
            telemetry_requested=True,
        ),
        now=100.0,
    )
    assert decision.allowed

    content = _safe_contract(
        telemetry=TelemetryPolicy(
            mode=TelemetryMode.OPT_IN,
            consent=True,
            destination="https://telemetry.invalid",
            fields=frozenset({"prompt"}),
        )
    )
    assert not content.is_safe


def test_retention_must_be_finite_and_expiring() -> None:
    assert RetentionPolicy(max_age_seconds=MAX_RETENTION_SECONDS).violations() == ()
    assert RetentionPolicy(max_age_seconds=None).violations()
    assert RetentionPolicy(max_age_seconds=MAX_RETENTION_SECONDS + 1).violations()
    assert RetentionPolicy(delete_on_expiry=False).violations()


def test_redaction_covers_nested_data_and_text_and_disabled_redaction_fails_closed() -> None:
    policy = RedactionPolicy()
    redacted = policy.redact(
        {
            "token": "canary-secret",
            "nested": {"password": "another-secret", "ok": "visible"},
            "message": "token=inline-secret status=ok",
        }
    )

    assert redacted["token"] == "[REDACTED]"
    assert redacted["nested"]["password"] == "[REDACTED]"
    assert redacted["nested"]["ok"] == "visible"
    assert "inline-secret" not in redacted["message"]
    assert not DesktopSecurityContract(redaction=RedactionPolicy(enabled=False)).is_safe
    assert RedactionPolicy(enabled=False).redact("canary") == "[REDACTED]"


def test_high_risk_requires_scoped_unexpired_approval() -> None:
    contract = _safe_contract()
    request = DesktopActionRequest(
        action="run-terminal",
        scope="workspace:a",
        permissions=frozenset({Permission.READ_WORKSPACE}),
        risk=RiskLevel.HIGH,
    )
    denied = contract.authorize(request, now=100.0)
    wrong_scope = contract.authorize(
        request,
        approval=RiskApproval(True, "alice", "maintenance", "workspace:b", 200.0),
        now=100.0,
    )
    approved = contract.authorize(
        request,
        approval=RiskApproval(True, "alice", "maintenance", "workspace:a", 200.0),
        now=100.0,
    )
    expired = contract.authorize(
        request,
        approval=RiskApproval(True, "alice", "maintenance", "workspace:a", 100.0),
        now=100.0,
    )

    assert not denied.allowed
    assert any(v.code is ViolationCode.RISK_APPROVAL_REQUIRED for v in denied.violations)
    assert not wrong_scope.allowed
    assert any(v.code is ViolationCode.INVALID_APPROVAL for v in wrong_scope.violations)
    assert approved.allowed
    assert not expired.allowed


def test_invalid_action_metadata_fails_closed() -> None:
    contract = _safe_contract()
    request = DesktopActionRequest(
        action="unknown-risk",
        scope="workspace:a",
        permissions=frozenset({"not-a-permission"}),  # type: ignore[arg-type]
        risk="not-a-risk",  # type: ignore[arg-type]
    )

    decision = contract.authorize(request, now=100.0)

    assert not decision.allowed
    assert any(v.code is ViolationCode.INVALID_SETTING for v in decision.violations)
