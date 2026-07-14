from agent.runtime_bridge import RuntimeBridgeContract
from tools.runtime_handshake import ProtocolRange


def test_runtime_bridge_contract_keeps_gate_ownership_explicit():
    bridge = RuntimeBridgeContract(
        agent_protocol=ProtocolRange(1, 2),
        runtime_protocol=ProtocolRange(2, 2),
        transport="local-mcp",
        required_schemas=("simplicio.run-event/v1",),
    )
    assert bridge.compatible
    assert bridge.to_dict()["gate_owner"] == "simplicio-runtime"
    assert bridge.to_dict()["mutations_require_gate"] is True
    assert len(bridge.content_hash()) == 64
