from agent.mcp_cli_compatibility_contract import (
    FALLBACK_READY,
    NOT_READY,
    READY,
    CommandCheck,
    Fallback,
    MCPCheck,
    build_certificate,
    from_dict,
    validate_certificate,
)


def _command(name="smoke", command="simplicio --version", passed=True):
    return CommandCheck(name, command, passed, "exit=0", 0 if passed else 1)


def _mcp(name="initialize", method="initialize", passed=True):
    return MCPCheck(name, method, passed, "request/response recorded")


def test_builds_ready_certificate_for_one_host():
    certificate = build_certificate(
        host="codex",
        provider="simplicio-runtime",
        version="3.32.5",
        command_checks=[_command()],
        mcp_checks=[_mcp()],
    )

    result = validate_certificate(certificate)
    assert certificate.readiness == READY
    assert len(certificate.evidence_hash) == 64
    assert result.valid is True
    assert result.ready is True
    assert result.reasons == ()


def test_missing_command_or_mcp_checks_fails_closed():
    missing_command = build_certificate(
        host="cursor",
        provider="runtime",
        version="1",
        command_checks=[],
        mcp_checks=[_mcp()],
    )
    missing_mcp = build_certificate(
        host="cursor",
        provider="runtime",
        version="1",
        command_checks=[_command()],
        mcp_checks=[],
    )

    assert missing_command.readiness == NOT_READY
    assert missing_mcp.readiness == NOT_READY
    assert validate_certificate(missing_command).ready is False
    assert validate_certificate(missing_mcp).ready is False


def test_failed_check_fails_closed():
    certificate = build_certificate(
        host="claude",
        provider="runtime",
        version="1",
        command_checks=[_command(passed=False)],
        mcp_checks=[_mcp()],
    )

    result = validate_certificate(certificate)
    assert certificate.readiness == NOT_READY
    assert result.ready is False
    assert "failed_command_check" in result.reasons


def test_explicit_cli_fallback_is_distinct_from_mcp_ready():
    command = _command(command="simplicio-mapper --version")
    certificate = build_certificate(
        host="vscode",
        provider="runtime",
        version="1",
        command_checks=[command],
        mcp_checks=[_mcp(passed=False)],
        fallback=Fallback("cli", command.command, "MCP server unavailable"),
    )

    result = validate_certificate(certificate)
    assert certificate.readiness == FALLBACK_READY
    assert result.ready is True
    assert certificate.fallback.mode == "cli"
    assert certificate.readiness != READY


def test_invalid_fallback_fails_closed():
    certificate = build_certificate(
        host="hermes",
        provider="runtime",
        version="1",
        command_checks=[_command()],
        mcp_checks=[_mcp()],
        fallback=Fallback("cli", "simplicio --wrong", "not proven"),
    )

    result = validate_certificate(certificate)
    assert result.ready is False
    assert "fallback_requires_failed_mcp_check" in result.reasons
    assert "fallback_command_not_proven" in result.reasons


def test_tampered_hash_and_readiness_are_not_trusted():
    certificate = build_certificate(
        host="generic-mcp",
        provider="runtime",
        version="1",
        command_checks=[_command()],
        mcp_checks=[_mcp()],
    )
    payload = certificate.to_dict()

    payload["evidence_hash"] = "0" * 64
    assert validate_certificate(from_dict(payload)).ready is False

    payload = certificate.to_dict()
    payload["readiness"] = NOT_READY
    result = validate_certificate(from_dict(payload))
    assert result.ready is False
    assert "readiness_mismatch" in result.reasons


def test_evidence_hash_is_deterministic_and_changes_with_evidence():
    kwargs = {
        "host": "codex",
        "provider": "runtime",
        "version": "1",
        "command_checks": [_command()],
        "mcp_checks": [_mcp()],
    }
    first = build_certificate(**kwargs)
    second = build_certificate(**kwargs)
    changed = build_certificate(**{**kwargs, "mcp_checks": [_mcp(method="tools/list")]})

    assert first.evidence_hash == second.evidence_hash
    assert first.evidence_hash != changed.evidence_hash


def test_missing_check_evidence_fails_closed():
    certificate = build_certificate(
        host="antigravity",
        provider="runtime",
        version="1",
        command_checks=[CommandCheck("smoke", "simplicio --version", True, "")],
        mcp_checks=[_mcp()],
    )

    result = validate_certificate(certificate)
    assert result.ready is False
    assert "command_check_0_missing_required_field" in result.reasons


def test_certificate_has_no_multi_host_certification_claim():
    certificate = build_certificate(
        host="claude",
        provider="runtime",
        version="1",
        command_checks=[_command()],
        mcp_checks=[_mcp()],
    )

    assert certificate.identity.host == "claude"
    assert "hosts" not in certificate.to_dict()
    assert "certified_hosts" not in certificate.to_dict()
