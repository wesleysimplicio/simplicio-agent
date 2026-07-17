"""Focused contracts for the Native 1.2 shadow/effect boundary."""

import json
from pathlib import Path

import pytest

from tools.shadow_effects import (
    DivergenceKind,
    EffectBlockedError,
    EffectDecision,
    EffectInterceptor,
    EffectKind,
    EffectRequest,
    FilesystemSentinel,
    NetworkSentinel,
    OverlayReceipt,
    ShadowOverlay,
    ShadowReceipt,
    UnknownEffectError,
    compare_effect_sequences,
)
from tools.transaction_primitives import SnapshotStore


FIXTURE_PATH = (
    Path(__file__).parents[2] / "fixtures" / "shadow" / "divergence_cases.json"
)


def _request(value: dict) -> EffectRequest:
    return EffectRequest.from_dict(value)


def test_effect_request_is_typed_and_canonical() -> None:
    request = EffectRequest(
        EffectKind.FS_READ,
        "read",
        "input.txt",
        {"encoding": "utf-8", "ordered": {"b": 2, "a": 1}},
        read_through=True,
    )

    assert request.kind is EffectKind.FS_READ
    assert request.is_read
    assert json.loads(request.to_json())["payload"] == {
        "encoding": "utf-8",
        "ordered": {"a": 1, "b": 2},
    }
    assert len(request.request_id) == 64


def test_unknown_effect_is_rejected_at_typed_boundary() -> None:
    with pytest.raises(UnknownEffectError):
        EffectRequest("filesystem_magic", "write")


def test_interceptor_fails_closed_for_unknown_without_callback() -> None:
    calls: list[str] = []
    interceptor = EffectInterceptor()

    result = interceptor.intercept(
        {"effect": "filesystem_magic", "operation": "write"},
        read_through=lambda _: calls.append("called"),
    )

    assert result.blocked
    assert not result.executed
    assert "unknown" in result.reason
    assert calls == []


def test_reads_use_explicit_read_through_only() -> None:
    interceptor = EffectInterceptor()
    request = EffectRequest(EffectKind.FS_READ, "read", "input.txt")

    result = interceptor.intercept(
        request, read_through=lambda item: item.target.upper()
    )

    assert result.allowed
    assert result.disposition == "read_through"
    assert result.value == "INPUT.TXT"

    blocked = interceptor.intercept(request)
    assert blocked.blocked
    assert "callback" in blocked.reason


def test_fs_writes_are_staged_in_disposable_overlay(tmp_path: Path) -> None:
    overlay = ShadowOverlay(tmp_path / "overlay")
    interceptor = EffectInterceptor(overlay=overlay)
    request = EffectRequest(
        EffectKind.FS_WRITE,
        "write",
        payload={"path": "nested/output.txt", "content": "shadow only"},
    )

    result = interceptor.intercept(request)

    assert result.allowed
    assert not result.executed
    assert overlay.read_bytes("nested/output.txt") == b"shadow only"
    assert not (tmp_path / "output.txt").exists()
    overlay.discard()
    assert not (tmp_path / "overlay" / "nested" / "output.txt").exists()


def test_overlay_can_mount_existing_snapshot_without_touching_source(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "input.txt").write_text("snapshot", encoding="utf-8")
    store = SnapshotStore(tmp_path / "store")
    manifest = store.create(source)

    overlay = ShadowOverlay.from_snapshot(store, manifest, tmp_path / "mounted")
    result = EffectInterceptor(overlay=overlay).intercept(
        EffectRequest(
            EffectKind.FS_WRITE,
            "write",
            payload={"path": "output.txt", "content": "overlay"},
        )
    )

    assert result.allowed
    assert (tmp_path / "mounted" / "input.txt").read_text(
        encoding="utf-8"
    ) == "snapshot"
    assert not (source / "output.txt").exists()


def test_external_effects_are_blocked_and_network_is_recorded() -> None:
    sentinel = NetworkSentinel()
    interceptor = EffectInterceptor(network_sentinel=sentinel)
    request = EffectRequest(EffectKind.NETWORK_HTTP, "GET", "https://example.invalid")

    result = interceptor.intercept(request)

    assert result.blocked
    assert sentinel.to_dict()["passed"]
    assert sentinel.to_dict()["blocked_attempts"][0]["target"] == request.target


def test_filesystem_sentinel_detects_host_drift(tmp_path: Path) -> None:
    target = tmp_path / "host"
    target.mkdir()
    (target / "state.txt").write_text("before", encoding="utf-8")
    sentinel = FilesystemSentinel.capture(target)

    (target / "state.txt").write_text("after", encoding="utf-8")
    checked = sentinel.check()

    assert not checked.passed
    assert checked.before.snapshot_id != checked.after.snapshot_id


def test_divergence_fixture_detects_all_four_contract_cases() -> None:
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    expected_kinds = {
        "addition": DivergenceKind.ADDITION,
        "missing": DivergenceKind.MISSING,
        "order": DivergenceKind.ORDER,
        "payload": DivergenceKind.PAYLOAD,
    }

    for case in fixture["cases"]:
        report = compare_effect_sequences(
            tuple(_request(value) for value in case["legacy"]),
            tuple(_request(value) for value in case["shadow"]),
        )
        assert not report.equivalent
        assert report.divergences[0].kind is expected_kinds[case["expected"]]
        assert report.to_dict()["schema"] == "simplicio.shadow-report/v1"


def test_equal_sequences_have_stable_report() -> None:
    request = EffectRequest(EffectKind.FS_READ, "read", "same.txt")

    first = compare_effect_sequences((request,), (request,))
    second = compare_effect_sequences((request,), (request,))

    assert first.equivalent
    assert first.to_json() == second.to_json()
    assert first.digest() == second.digest()


def test_hbp_shadow_receipt_requires_passing_evidence() -> None:
    request = EffectRequest(EffectKind.FS_READ, "read", "same.txt")
    report = compare_effect_sequences((request,), (request,))
    filesystem = {
        "kind": "filesystem",
        "passed": True,
        "before_digest": "a" * 64,
        "after_digest": "a" * 64,
    }
    network = {"kind": "network", "passed": True, "blocked_attempts": []}
    receipt = ShadowReceipt("a" * 64, report, filesystem, network)

    assert receipt.to_dict()["hbp_schema"] == "simplicio.hbp-receipt/v1"
    assert receipt.to_dict()["report_digest"] == report.digest()
    assert len(receipt.digest) == 64

    with pytest.raises(ValueError, match="passing shadow receipt"):
        ShadowReceipt(
            "a" * 64, compare_effect_sequences((request,), ()), filesystem, network
        )


# --- Additional coverage: EffectRequest validation branches ----------------


def test_canonical_rejects_non_serializable_payload() -> None:
    with pytest.raises(ValueError, match="JSON serializable"):
        EffectRequest(EffectKind.FS_READ, "read", "x", {"bad": object()})


def test_effect_request_rejects_empty_operation() -> None:
    with pytest.raises(ValueError, match="operation must be non-empty"):
        EffectRequest(EffectKind.FS_READ, "   ")


def test_effect_request_rejects_non_mapping_payload() -> None:
    with pytest.raises(TypeError, match="payload must be a mapping"):
        EffectRequest(EffectKind.FS_READ, "read", "x", payload=["not", "a", "map"])  # type: ignore[arg-type]


def test_effect_request_rejects_read_through_on_write_effect() -> None:
    with pytest.raises(ValueError, match="only read effects may use read-through"):
        EffectRequest(EffectKind.FS_WRITE, "write", "x", read_through=True)


def test_effect_request_from_dict_rejects_unsupported_schema() -> None:
    with pytest.raises(ValueError, match="unsupported effect request schema"):
        EffectRequest.from_dict({"schema": "other/v1", "effect": "fs_read", "operation": "read"})


def test_overlay_receipt_to_dict_round_trips() -> None:
    receipt = OverlayReceipt("path.txt", "write", True)
    assert receipt.to_dict() == {"path": "path.txt", "operation": "write", "applied": True}


def test_overlay_root_must_be_directory(tmp_path: Path) -> None:
    conflicting = tmp_path / "not_a_dir"
    conflicting.write_text("file, not dir", encoding="utf-8")

    with pytest.raises(ValueError, match="overlay root must be a directory"):
        ShadowOverlay(conflicting)


def test_overlay_rejects_absolute_and_traversal_paths(tmp_path: Path) -> None:
    overlay = ShadowOverlay(tmp_path / "overlay")

    with pytest.raises(ValueError, match="within its root"):
        overlay._path("")
    with pytest.raises(ValueError, match="within its root"):
        overlay._path(str(tmp_path / "absolute.txt"))
    with pytest.raises(ValueError, match="within its root"):
        overlay._path("../escape.txt")


def test_overlay_apply_rejects_non_fs_write_effect(tmp_path: Path) -> None:
    overlay = ShadowOverlay(tmp_path / "overlay")
    request = EffectRequest(EffectKind.FS_READ, "read", "x")

    with pytest.raises(ValueError, match="only accepts fs_write"):
        overlay.apply(request)


def test_overlay_write_requires_content(tmp_path: Path) -> None:
    overlay = ShadowOverlay(tmp_path / "overlay")
    request = EffectRequest(EffectKind.FS_WRITE, "write", payload={"path": "a.txt"})

    with pytest.raises(ValueError, match="requires payload.content"):
        overlay.apply(request)


def test_overlay_write_accepts_bytes_content(tmp_path: Path) -> None:
    # EffectRequest itself only accepts JSON-serializable payloads, so bytes
    # content can never arrive through the public constructor. The overlay's
    # bytes branch exists for callers that build a request object directly
    # (e.g. deserializing from a non-JSON internal channel); simulate that by
    # bypassing the frozen dataclass's normal construction path.
    overlay = ShadowOverlay(tmp_path / "overlay")
    request = EffectRequest(
        EffectKind.FS_WRITE, "write", payload={"path": "a.bin", "content": "placeholder"}
    )
    object.__setattr__(request, "payload", {"path": "a.bin", "content": b"\x00\x01"})

    overlay.apply(request)

    assert overlay.read_bytes("a.bin") == b"\x00\x01"


def test_overlay_write_rejects_non_text_non_bytes_content(tmp_path: Path) -> None:
    overlay = ShadowOverlay(tmp_path / "overlay")
    request = EffectRequest(
        EffectKind.FS_WRITE, "write", payload={"path": "a.txt", "content": 12345}
    )

    with pytest.raises(TypeError, match="text or bytes"):
        overlay.apply(request)


def test_overlay_delete_removes_existing_file(tmp_path: Path) -> None:
    overlay = ShadowOverlay(tmp_path / "overlay")
    write_request = EffectRequest(
        EffectKind.FS_WRITE, "write", payload={"path": "a.txt", "content": "x"}
    )
    overlay.apply(write_request)
    delete_request = EffectRequest(EffectKind.FS_WRITE, "delete", payload={"path": "a.txt"})

    receipt = overlay.apply(delete_request)

    assert receipt.applied
    assert not (overlay.root / "a.txt").exists()


def test_overlay_delete_of_missing_file_is_a_noop(tmp_path: Path) -> None:
    overlay = ShadowOverlay(tmp_path / "overlay")
    delete_request = EffectRequest(EffectKind.FS_WRITE, "remove", payload={"path": "missing.txt"})

    receipt = overlay.apply(delete_request)

    assert receipt.applied


def test_overlay_delete_cannot_remove_a_directory(tmp_path: Path) -> None:
    overlay = ShadowOverlay(tmp_path / "overlay")
    (overlay.root / "adir").mkdir()
    delete_request = EffectRequest(EffectKind.FS_WRITE, "unlink", payload={"path": "adir"})

    with pytest.raises(ValueError, match="cannot remove a directory"):
        overlay.apply(delete_request)


def test_overlay_rejects_unsupported_operation(tmp_path: Path) -> None:
    overlay = ShadowOverlay(tmp_path / "overlay")
    request = EffectRequest(EffectKind.FS_WRITE, "rename", payload={"path": "a.txt"})

    with pytest.raises(ValueError, match="unsupported overlay operation"):
        overlay.apply(request)


def test_overlay_discard_removes_nested_directories(tmp_path: Path) -> None:
    overlay = ShadowOverlay(tmp_path / "overlay")
    nested_request = EffectRequest(
        EffectKind.FS_WRITE, "write", payload={"path": "nested/dir/file.txt", "content": "x"}
    )
    overlay.apply(nested_request)
    assert (overlay.root / "nested").is_dir()

    overlay.discard()

    assert list(overlay.root.iterdir()) == []
    assert overlay.receipts == []


def test_effect_decision_to_dict_reports_overlay_and_request(tmp_path: Path) -> None:
    overlay = ShadowOverlay(tmp_path / "overlay")
    request = EffectRequest(
        EffectKind.FS_WRITE, "write", payload={"path": "a.txt", "content": "x"}
    )
    receipt = overlay.apply(request)
    decision = EffectDecision(request, "overlay", False, False, overlay=receipt)

    body = decision.to_dict()

    assert body["request"]["effect"] == "fs_write"
    assert body["overlay"] == receipt.to_dict()
    assert decision.allowed


def test_network_sentinel_block_raises_and_records_attempt() -> None:
    sentinel = NetworkSentinel()
    request = EffectRequest(EffectKind.NETWORK_HTTP, "GET", "https://example.invalid")

    with pytest.raises(EffectBlockedError, match="network effect blocked"):
        sentinel.block(request, reason="test reason")

    assert sentinel.attempts[0]["reason"] == "test reason"
    assert sentinel.attempts[0]["target"] == request.target


def test_filesystem_sentinel_to_dict_reports_digests(tmp_path: Path) -> None:
    target = tmp_path / "host"
    target.mkdir()
    (target / "state.txt").write_text("before", encoding="utf-8")
    sentinel = FilesystemSentinel.capture(target)
    checked = sentinel.check()

    body = checked.to_dict()

    assert body["kind"] == "filesystem"
    assert body["passed"] is True
    assert body["before_digest"] == checked.before.snapshot_id
    assert body["after_digest"] == checked.after.snapshot_id


def test_fs_write_without_overlay_is_blocked_and_not_sentineled() -> None:
    interceptor = EffectInterceptor()
    request = EffectRequest(
        EffectKind.FS_WRITE, "write", payload={"path": "a.txt", "content": "x"}
    )

    result = interceptor.intercept(request)

    assert result.blocked
    assert result.reason == "external effect blocked in shadow mode"
    # fs_write is not one of the network-sentineled kinds even when blocked.
    assert interceptor.network_sentinel.attempts == []


def test_compare_sequences_detects_payload_divergence_at_same_position() -> None:
    legacy = EffectRequest(EffectKind.FS_WRITE, "write", "a.txt", {"content": "old"})
    shadow = EffectRequest(EffectKind.FS_WRITE, "write", "a.txt", {"content": "new"})

    report = compare_effect_sequences((legacy,), (shadow,))

    assert not report.equivalent
    assert report.divergences[0].kind is DivergenceKind.PAYLOAD


def test_shadow_receipt_rejects_invalid_verdict() -> None:
    request = EffectRequest(EffectKind.FS_READ, "read", "same.txt")
    report = compare_effect_sequences((request,), (request,))
    filesystem = {"kind": "filesystem", "passed": True}
    network = {"kind": "network", "passed": True}

    with pytest.raises(ValueError, match="verdict must be pass, fail, or blocked"):
        ShadowReceipt("a" * 64, report, filesystem, network, verdict="maybe")


def test_overlay_discard_removes_top_level_file(tmp_path: Path) -> None:
    overlay = ShadowOverlay(tmp_path / "overlay")
    request = EffectRequest(
        EffectKind.FS_WRITE, "write", payload={"path": "top.txt", "content": "x"}
    )
    overlay.apply(request)
    assert (overlay.root / "top.txt").is_file()

    overlay.discard()

    assert list(overlay.root.iterdir()) == []


def test_overlay_path_resolves_outside_root_via_symlink_is_rejected(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    overlay = ShadowOverlay(tmp_path / "overlay")
    link = overlay.root / "escape"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are not permitted in this environment")

    with pytest.raises(ValueError, match="within its root"):
        overlay._path("escape/file.txt")


def test_interceptor_records_unknown_effect_only_for_mapping_inputs() -> None:
    class SchemaMismatch:
        """Duck-types .get() like a mapping but is not registered as one."""

        def get(self, key, default=None):
            if key == "schema":
                return "not-the-real-schema"
            return default

    interceptor = EffectInterceptor()

    result = interceptor.intercept(SchemaMismatch())

    assert result.blocked
    assert "unsupported effect request schema" in result.reason
    assert interceptor.unknown_effects == []


def test_compare_sequences_detects_order_divergence_with_unequal_lengths() -> None:
    read_a = EffectRequest(EffectKind.FS_READ, "read", "a.txt")
    read_b = EffectRequest(EffectKind.FS_READ, "read", "b.txt")
    read_c = EffectRequest(EffectKind.FS_READ, "read", "c.txt")

    # legacy has 2 requests, shadow has 3: b.txt is pulled forward in shadow,
    # so the comparator must detect it as reordered rather than added/missing.
    report = compare_effect_sequences((read_a, read_b), (read_b, read_a, read_c))

    assert not report.equivalent
    assert report.divergences[0].kind is DivergenceKind.ORDER


def test_compare_sequences_detects_payload_divergence_with_different_target() -> None:
    legacy = EffectRequest(EffectKind.FS_WRITE, "write", "a.txt", {"content": "x"})
    shadow = EffectRequest(EffectKind.FS_WRITE, "write", "b.txt", {"content": "y"})

    report = compare_effect_sequences((legacy,), (shadow,))

    assert not report.equivalent
    assert report.divergences[0].kind is DivergenceKind.PAYLOAD


def test_shadow_receipt_rejects_non_sha256_snapshot_digest() -> None:
    request = EffectRequest(EffectKind.FS_READ, "read", "same.txt")
    report = compare_effect_sequences((request,), (request,))
    filesystem = {"kind": "filesystem", "passed": True}
    network = {"kind": "network", "passed": True}

    with pytest.raises(ValueError, match="snapshot_digest must be a sha256 digest"):
        ShadowReceipt("too-short", report, filesystem, network)
