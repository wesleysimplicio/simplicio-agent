"""Focused contracts for the Native 1.2 shadow/effect boundary."""

import json
from pathlib import Path

import pytest

from tools.shadow_effects import (
    DivergenceKind,
    EffectInterceptor,
    EffectKind,
    EffectRequest,
    FilesystemSentinel,
    NetworkSentinel,
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
