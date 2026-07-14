import json
from pathlib import Path

from gateway.native_bridge import (
    BridgeLease,
    BridgeLifecyclePhase,
    BridgeReceiptStatus,
    NativeGatewayBridge,
    NativeBridgeRequest,
    NATIVE_BRIDGE_SCHEMA,
)


def _request(lease, payload=None):
    return {
        "schema": NATIVE_BRIDGE_SCHEMA,
        "request_id": "r1",
        "operation": "echo",
        "payload": payload or {"x": 1},
        "lease": lease.to_dict(),
    }


def test_dispatch_and_deterministic_receipt():
    now = [100.0]
    bridge = NativeGatewayBridge(
        lambda op, payload: {"op": op, **payload},
        bridge_id="b",
        ttl_seconds=10,
        clock=lambda: now[0],
    )
    first = bridge.dispatch(_request(bridge.lease))
    second = bridge.dispatch(_request(bridge.lease))
    assert first["ok"] and first["value"] == {"op": "echo", "x": 1}
    assert second["sequence"] == 2
    assert bridge.health()["lease_digest"] == bridge.health()["lease_digest"]


def test_expiry_is_inclusive_and_handler_is_not_called():
    now = [100.0]
    calls = []
    bridge = NativeGatewayBridge(
        lambda op, payload: calls.append(op),
        bridge_id="b",
        ttl_seconds=10,
        clock=lambda: now[0],
    )
    now[0] = bridge.lease.expires_at
    result = bridge.dispatch(_request(bridge.lease))
    assert result == {
        "schema": NATIVE_BRIDGE_SCHEMA,
        "status": "expired",
        "ok": False,
        "bridge_id": "b",
        "sequence": 0,
        "request_id": "r1",
        "error": "lease_expired",
    }
    assert calls == []


def test_isolation_and_payload_limits_fail_closed():
    calls = []
    bridge = NativeGatewayBridge(
        lambda op, payload: calls.append(payload),
        bridge_id="b",
        ttl_seconds=10,
        clock=lambda: 100.0,
        max_payload_bytes=8,
    )
    wrong = BridgeLease.issue(10, now=100.0, bridge_id="other")
    assert bridge.dispatch(_request(wrong))["error"] == "wrong_bridge_id"
    assert (
        bridge.dispatch(_request(bridge.lease, {"too": "large"}))["error"]
        == "payload_too_large"
    )
    assert calls == []


def test_close_is_idempotent_and_blocks_dispatch():
    bridge = NativeGatewayBridge(
        lambda op, payload: payload, bridge_id="b", ttl_seconds=10, clock=lambda: 100.0
    )
    assert bridge.close()["ok"] is True
    assert bridge.close()["status"] == "closed"
    assert bridge.dispatch(_request(bridge.lease))["error"] == "bridge_closed"


def test_request_round_trip_is_json_safe():
    lease = BridgeLease.issue(10, now=100.0, bridge_id="b")
    request = NativeBridgeRequest.from_dict(_request(lease))
    assert request.to_dict() == _request(lease)


def test_typed_lifecycle_and_receipt_projection_preserve_legacy_shape():
    now = [100.0]
    bridge = NativeGatewayBridge(
        lambda op, payload: payload,
        bridge_id="typed",
        ttl_seconds=10,
        clock=lambda: now[0],
    )

    assert bridge.lifecycle().phase is BridgeLifecyclePhase.ACTIVE
    receipt = bridge.dispatch_receipt(_request(bridge.lease))
    assert receipt.status is BridgeReceiptStatus.OK
    legacy_receipt = bridge.dispatch(_request(bridge.lease))
    assert receipt.to_dict()["schema"] == legacy_receipt["schema"]
    assert receipt.to_dict()["status"] == legacy_receipt["status"]
    assert bridge.lifecycle().to_dict()["sequence"] == 2

    now[0] = bridge.lease.expires_at
    assert bridge.lifecycle().phase is BridgeLifecyclePhase.EXPIRED


def test_rollback_is_fail_closed_and_idempotent():
    calls = []
    bridge = NativeGatewayBridge(
        lambda op, payload: calls.append(payload),
        bridge_id="rollback",
        ttl_seconds=10,
        clock=lambda: 100.0,
    )

    first = bridge.rollback("smoke_failed")
    second = bridge.rollback("a_different_reason")
    blocked = bridge.dispatch(_request(bridge.lease))

    assert (
        first
        == second
        == {
            "schema": NATIVE_BRIDGE_SCHEMA,
            "status": "rolled_back",
            "ok": False,
            "bridge_id": "rollback",
            "sequence": 0,
            "error": "smoke_failed",
        }
    )
    assert blocked["status"] == "rolled_back"
    assert calls == []
    assert bridge.lifecycle().phase is BridgeLifecyclePhase.ROLLED_BACK


def test_deterministic_receipt_fixture_covers_smoke_expiry_and_rollback():
    fixture_path = (
        Path(__file__).resolve().parents[2]
        / "fixtures"
        / "gateway"
        / "native_bridge_receipts.json"
    )
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    now = [100.0]

    smoke = NativeGatewayBridge(
        lambda op, payload: {"op": op, **payload},
        bridge_id="smoke",
        ttl_seconds=10,
        clock=lambda: now[0],
    )
    smoke_result = smoke.dispatch({
        "schema": NATIVE_BRIDGE_SCHEMA,
        "request_id": "smoke-1",
        "operation": "echo",
        "payload": {"message": "ok"},
        "lease": smoke.lease.to_dict(),
    })

    expiry = NativeGatewayBridge(
        lambda op, payload: {"op": op, **payload},
        bridge_id="expiry",
        ttl_seconds=10,
        clock=lambda: now[0],
    )
    now[0] = expiry.lease.expires_at
    expiry_result = expiry.dispatch({
        "schema": NATIVE_BRIDGE_SCHEMA,
        "request_id": "expiry-1",
        "operation": "echo",
        "payload": {"message": "late"},
        "lease": expiry.lease.to_dict(),
    })

    rollback = NativeGatewayBridge(
        lambda op, payload: {"op": op, **payload},
        bridge_id="rollback",
        ttl_seconds=10,
        clock=lambda: 100.0,
    )
    rollback_result = rollback.rollback("smoke_failed")

    assert [smoke_result, expiry_result, rollback_result] == fixture["receipts"]
