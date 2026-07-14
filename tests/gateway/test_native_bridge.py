from gateway.native_bridge import (
    BridgeLease,
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
