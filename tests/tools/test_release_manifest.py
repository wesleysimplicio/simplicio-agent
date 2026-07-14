from tools.release_manifest import (
    RELEASE_MANIFEST_SCHEMA,
    ROLLBACK_CONTRACT_SCHEMA,
    build_release_manifest,
    build_rollback_contract,
    evaluate_release_contract,
    validate_release_manifest,
    validate_rollback_contract,
)


def _manifest():
    return build_release_manifest(
        version="0.25.0",
        source_commit="abc123",
        artifact={
            "name": "simplicio-agent.whl",
            "kind": "wheel",
            "channel": "pypi",
            "digest": "sha256:" + "a" * 64,
        },
        runtime={
            "name": "simplicio-runtime",
            "version": "3.5.0",
            "digest": "sha256:" + "b" * 64,
        },
        files=[{"path": "simplicio_agent/__init__.py", "digest": "sha256:" + "c" * 64}],
    )


def test_release_manifest_is_digest_pinned_and_canonical():
    manifest = _manifest()
    assert manifest["schema"] == RELEASE_MANIFEST_SCHEMA
    assert validate_release_manifest(manifest) == []
    changed = dict(manifest)
    changed["source_commit"] = "changed"
    assert (
        "manifest_digest does not match manifest contents"
        in validate_release_manifest(changed)
    )


def test_release_manifest_rejects_legacy_runtime_identity():
    manifest = _manifest()
    manifest["runtime"] = dict(manifest["runtime"], name="hermes-runtime")
    assert "runtime.name must be simplicio-runtime" in validate_release_manifest(
        manifest
    )


def test_rollback_contract_requires_restored_agent_digest_and_state():
    manifest = _manifest()
    rollback = build_rollback_contract(
        from_manifest_digest="sha256:" + "d" * 64,
        to_manifest_digest=manifest["manifest_digest"],
        restored_manifest_digest="sha256:" + "e" * 64,
        receipts=["rollback.json"],
        state_preserved=True,
        restored_identity={
            "name": "simplicio-agent",
            "manifest_digest": "sha256:" + "e" * 64,
        },
    )
    assert rollback["schema"] == ROLLBACK_CONTRACT_SCHEMA
    assert validate_rollback_contract(rollback) == []
    rollback["state_preserved"] = False
    assert "state_preserved must be true" in validate_rollback_contract(rollback)


def test_evaluation_is_fail_closed():
    manifest = _manifest()
    report = evaluate_release_contract(manifest)
    assert report["ok"] is True
    manifest["manifest_digest"] = "sha256:" + "0" * 64
    assert evaluate_release_contract(manifest)["ok"] is False
