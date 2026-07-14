import json
from datetime import date

from tools.identity_scan import (
    IDENTITY_MANIFEST_SCHEMA,
    report,
    scan_text,
    validate_manifest,
)


def manifest(**entry):
    return {"schema": IDENTITY_MANIFEST_SCHEMA, "version": 1, "entries": [entry]}


def test_undeclared_legacy_reference_blocks_no_legacy_scan():
    findings = scan_text(
        "src/main.py",
        "name = 'hermes-agent'\n",
        {"schema": IDENTITY_MANIFEST_SCHEMA, "version": 1, "entries": []},
        today=date(2026, 7, 14),
    )
    assert report(findings)["ok"] is False
    assert findings[0].classification == "legacy"


def test_expired_compatibility_entry_blocks():
    findings = scan_text(
        "compatibility/alias.py",
        "name = 'hermes-agent'\n",
        manifest(
            term="hermes-agent",
            path_glob="compatibility/*",
            classification="compatibility",
            owner="test",
            reason="temporary",
            expiry="2026-01-01",
        ),
        today=date(2026, 7, 14),
    )
    assert findings[0].classification == "expired"
    assert report(findings)["blocking_count"] == 1


def test_legal_attribution_is_non_blocking_and_manifest_validates():
    m = manifest(
        term="hermes",
        path_glob="LICENSE",
        classification="legal_attribution",
        owner="project",
        reason="required",
    )
    assert validate_manifest(m, today=date(2026, 7, 14)) == []
    findings = scan_text("LICENSE", "Hermes Project\n", m, today=date(2026, 7, 14))
    assert report(findings)["ok"] is True


def test_report_digest_is_stable():
    m = {"schema": IDENTITY_MANIFEST_SCHEMA, "version": 1, "entries": []}
    first = report(scan_text("x.txt", "hermes\n", m))
    second = report(scan_text("x.txt", "hermes\n", m))
    assert first["digest"] == second["digest"]


def test_public_install_reference_blocks_but_migration_context_is_allowed():
    empty = {"schema": IDENTITY_MANIFEST_SCHEMA, "version": 1, "entries": []}
    public = scan_text(
        "docs/quickstart.md",
        "Install with `pip install hermes-agent`.\n",
        empty,
        today=date(2026, 7, 14),
    )
    assert report(public)["ok"] is False

    migration = scan_text(
        "docs/migration/hermes-to-simplicio.md",
        "The legacy `hermes-agent` alias remains supported during migration.\n",
        manifest(
            term="hermes-agent",
            path_glob="docs/migration/*",
            classification="compatibility",
            owner="release",
            reason="documented migration alias",
            expiry="2027-01-01",
        ),
        today=date(2026, 7, 14),
    )
    assert report(migration)["ok"] is True
