"""Tests for the distributed node host wire protocol.

These tests assert the **contract** from ADR-0006 / overview.md: that the four
wire types and the capability addressing record construct, validate, and
round-trip (msgspec JSON) exactly as the architecture requires. There is no
network, no gateway, and no agent-loop dependency -- the protocol is pure data,
so the tests are real (no mocks) and exercise every documented invariant:

* mandatory ``AgentTerms`` guardrails (reject-on-absence),
* ``CapabilitySpec`` authority/lane enum validation,
* ``NodeRegister`` protocol-major-mismatch rejection,
* ``TaskDispatch`` / ``TaskResult`` field validity,
* ``HealthPing`` liveness thresholds -> degraded/evicted state machine,
* msgspec JSON encode/decode symmetry for all four message types.
"""

import dataclasses
import msgspec
import pytest

from agent.distributed import (
    AgentTerms,
    CapabilitySpec,
    HealthPing,
    NodeRegister,
    PROTOCOL_VERSION,
    TaskDispatch,
    TaskResult,
    TaskStatus,
    WIRE_TYPES,
    HEALTH_DEGRADED_MISSING,
    HEALTH_EVICTED_MISSING,
    is_protocol_compatible,
    node_health_state,
    protocol_major,
)


# --------------------------------------------------------------------------
# Protocol version
# --------------------------------------------------------------------------
def test_protocol_version_is_semver() -> None:
    assert protocol_major(PROTOCOL_VERSION) == PROTOCOL_VERSION.split(".", 1)[0]


def test_compatible_protocol_major() -> None:
    assert is_protocol_compatible("1.0") is True
    assert is_protocol_compatible("1.4.2") is True


def test_incompatible_protocol_major_rejected() -> None:
    assert is_protocol_compatible("2.0") is False
    assert is_protocol_compatible("0.9") is False
    assert is_protocol_compatible("") is False


# --------------------------------------------------------------------------
# AgentTerms (mandatory guardrails)
# --------------------------------------------------------------------------
def test_agent_terms_accepts_valid() -> None:
    t = AgentTerms(cpu_quota_pct=50, disk_quota_mb=256, timeout_s=30)
    assert t.cpu_quota_pct == 50
    assert t.timeout_s == 30


def test_agent_terms_rejects_missing_quota() -> None:
    with pytest.raises(ValueError):
        AgentTerms(cpu_quota_pct=None, disk_quota_mb=256)  # type: ignore[arg-type]


def test_agent_terms_rejects_missing_disk() -> None:
    with pytest.raises(ValueError):
        AgentTerms(cpu_quota_pct=50, disk_quota_mb=None)  # type: ignore[arg-type]


def test_agent_terms_rejects_bad_cpu_range() -> None:
    with pytest.raises(ValueError):
        AgentTerms(cpu_quota_pct=150, disk_quota_mb=256)


def test_agent_terms_rejects_negative_disk() -> None:
    with pytest.raises(ValueError):
        AgentTerms(cpu_quota_pct=50, disk_quota_mb=-1)


# --------------------------------------------------------------------------
# CapabilitySpec
# --------------------------------------------------------------------------
def _cap() -> CapabilitySpec:
    return CapabilitySpec(
        yool_id="capability.desktop.system.run",
        authority="ops",
        lane="fast",
        agent_terms=AgentTerms(cpu_quota_pct=80, disk_quota_mb=512),
    )


def test_capability_spec_accepts_valid() -> None:
    assert _cap().yool_id == "capability.desktop.system.run"


@pytest.mark.parametrize("authority", ["dev", "ops", "review", "audit"])
def test_capability_spec_valid_authorities(authority: str) -> None:
    c = CapabilitySpec(
        yool_id="cap.surf.verb",
        authority=authority,
        lane="slow",
        agent_terms=AgentTerms(cpu_quota_pct=10, disk_quota_mb=10),
    )
    assert c.authority == authority


def test_capability_spec_rejects_bad_authority() -> None:
    with pytest.raises(ValueError):
        CapabilitySpec(
            yool_id="cap.surf.verb",
            authority="root",
            lane="fast",
            agent_terms=AgentTerms(cpu_quota_pct=10, disk_quota_mb=10),
        )


@pytest.mark.parametrize("lane", ["fast", "slow", "background"])
def test_capability_spec_valid_lanes(lane: str) -> None:
    c = CapabilitySpec(
        yool_id="cap.surf.verb",
        authority="dev",
        lane=lane,
        agent_terms=AgentTerms(cpu_quota_pct=10, disk_quota_mb=10),
    )
    assert c.lane == lane


def test_capability_spec_rejects_bad_lane() -> None:
    with pytest.raises(ValueError):
        CapabilitySpec(
            yool_id="cap.surf.verb",
            authority="dev",
            lane="realtime",
            agent_terms=AgentTerms(cpu_quota_pct=10, disk_quota_mb=10),
        )


def test_capability_spec_rejects_empty_yool_id() -> None:
    with pytest.raises(ValueError):
        CapabilitySpec(
            yool_id="",
            authority="dev",
            lane="fast",
            agent_terms=AgentTerms(cpu_quota_pct=10, disk_quota_mb=10),
        )


# --------------------------------------------------------------------------
# NodeRegister
# --------------------------------------------------------------------------
def test_node_register_accepts_valid() -> None:
    reg = NodeRegister(
        node_id="node-1",
        surface="desktop",
        capabilities=[_cap()],
        auth_token="tok-abc",
        protocol_version=PROTOCOL_VERSION,
    )
    assert reg.node_id == "node-1"
    assert len(reg.capabilities) == 1


def test_node_register_rejects_major_mismatch() -> None:
    with pytest.raises(ValueError):
        NodeRegister(
            node_id="node-1",
            surface="desktop",
            capabilities=[_cap()],
            auth_token="tok-abc",
            protocol_version="2.0",
        )


def test_node_register_rejects_empty_node_id() -> None:
    with pytest.raises(ValueError):
        NodeRegister(
            node_id="",
            surface="desktop",
            capabilities=[_cap()],
            auth_token="tok-abc",
            protocol_version=PROTOCOL_VERSION,
        )


# --------------------------------------------------------------------------
# TaskDispatch
# --------------------------------------------------------------------------
def test_task_dispatch_accepts_valid() -> None:
    d = TaskDispatch(
        task_id="t-1",
        capability="capability.desktop.system.run",
        payload={"cmd": "echo hi"},
        approval_token="approval-xyz",
        deadline_s=30.0,
        idempotency_key="idk-1",
    )
    assert d.task_id == "t-1"
    assert d.payload == {"cmd": "echo hi"}


def test_task_dispatch_allows_none_approval_token() -> None:
    d = TaskDispatch(
        task_id="t-2",
        capability="capability.browser.open",
        payload=None,
        approval_token=None,
        deadline_s=10.0,
        idempotency_key="idk-2",
    )
    assert d.approval_token is None


def test_task_dispatch_rejects_bad_deadline() -> None:
    with pytest.raises(ValueError):
        TaskDispatch(
            task_id="t-3",
            capability="cap.surf.verb",
            payload={},
            approval_token=None,
            deadline_s=0.0,
            idempotency_key="idk-3",
        )


# --------------------------------------------------------------------------
# TaskResult
# --------------------------------------------------------------------------
def test_task_result_accepts_ok() -> None:
    r = TaskResult(
        task_id="t-1",
        status=TaskStatus.OK,
        result_payload={"rc": 0},
        error=None,
        elapsed_ms=12.5,
        node_id="node-1",
    )
    assert r.status is TaskStatus.OK


def test_task_result_requires_error_on_error_status() -> None:
    with pytest.raises(ValueError):
        TaskResult(
            task_id="t-1",
            status=TaskStatus.ERROR,
            result_payload=None,
            error=None,
            elapsed_ms=1.0,
            node_id="node-1",
        )


def test_task_result_error_status_with_error_ok() -> None:
    r = TaskResult(
        task_id="t-1",
        status=TaskStatus.ERROR,
        result_payload=None,
        error="boom",
        elapsed_ms=1.0,
        node_id="node-1",
    )
    assert r.error == "boom"


def test_task_status_enum_values() -> None:
    assert {s.value for s in TaskStatus} == {"ok", "error", "timeout", "denied"}


# --------------------------------------------------------------------------
# HealthPing + failover state machine
# --------------------------------------------------------------------------
def test_health_ping_accepts_valid() -> None:
    p = HealthPing(
        node_id="node-1",
        ts=1000.0,
        inflight_count=2,
        cpu_pct=30.0,
        mem_pct=40.0,
        disk_pct=10.0,
    )
    assert p.inflight_count == 2


def test_health_ping_rejects_negative_inflight() -> None:
    with pytest.raises(ValueError):
        HealthPing(
            node_id="node-1",
            ts=1000.0,
            inflight_count=-1,
            cpu_pct=30.0,
            mem_pct=40.0,
            disk_pct=10.0,
        )


def test_node_health_state_machine() -> None:
    assert node_health_state(0) == "healthy"
    assert node_health_state(HEALTH_DEGRADED_MISSING - 1) == "healthy"
    assert node_health_state(HEALTH_DEGRADED_MISSING) == "degraded"
    assert node_health_state(HEALTH_EVICTED_MISSING - 1) == "degraded"
    assert node_health_state(HEALTH_EVICTED_MISSING) == "evicted"
    assert node_health_state(HEALTH_EVICTED_MISSING + 10) == "evicted"


# --------------------------------------------------------------------------
# msgspec round-trip (wire format)
# --------------------------------------------------------------------------
def _instances() -> dict[type, object]:
    return {
        NodeRegister: NodeRegister(
            node_id="node-1",
            surface="desktop",
            capabilities=[_cap()],
            auth_token="tok",
            protocol_version=PROTOCOL_VERSION,
        ),
        TaskDispatch: TaskDispatch(
            task_id="t-1",
            capability="capability.desktop.system.run",
            payload={"cmd": "echo hi"},
            approval_token="appr",
            deadline_s=30.0,
            idempotency_key="idk",
        ),
        TaskResult: TaskResult(
            task_id="t-1",
            status=TaskStatus.OK,
            result_payload={"rc": 0},
            error=None,
            elapsed_ms=12.5,
            node_id="node-1",
        ),
        HealthPing: HealthPing(
            node_id="node-1",
            ts=1000.0,
            inflight_count=2,
            cpu_pct=30.0,
            mem_pct=40.0,
            disk_pct=10.0,
        ),
    }


@pytest.mark.parametrize("msg_type", WIRE_TYPES)
def test_msgspec_roundtrip(msg_type: type) -> None:
    obj = _instances()[msg_type]
    buf = msgspec.json.encode(obj)
    decoded = msgspec.json.decode(buf, type=msg_type)
    assert decoded == obj
    assert dataclasses.is_dataclass(decoded)


def test_wire_types_are_slots_frozen() -> None:
    for t in WIRE_TYPES:
        assert dataclasses.is_dataclass(t)
        inst = _instances()[t]
        first_field = dataclasses.fields(t)[0].name
        with pytest.raises((AttributeError, dataclasses.FrozenInstanceError, TypeError)):
            setattr(inst, first_field, "mutated")  # type: ignore[arg-defined]
