from agent.prompt_zones import InferenceLease, InvalidationReason, PromptZones


class FakeRuntime:
    def __init__(self):
        self.acquires = []
        self.releases = []

    def acquire(self, session_id, prefix_sha256, generation):
        self.acquires.append((session_id, prefix_sha256, generation))
        return {"lease_id": f"opaque-{len(self.acquires)}", "slot_id": "must-not-leak"}

    def release(self, lease_id):
        self.releases.append(lease_id)


def test_prefix_is_byte_stable_and_tail_mutations_are_isolated():
    zones = PromptZones({"identity": "agent", "policy": ["safe"]}, {"messages": ["one"]})
    before = zones.prefix_bytes
    digest = zones.prefix_sha256
    zones.set_variable("messages", ["two"])
    assert zones.prefix_bytes == before
    assert zones.prefix_sha256 == digest
    assert zones.variable_tail_bytes != before


def test_canonical_encoding_is_order_stable():
    left = PromptZones({"policy": "safe", "identity": "agent"})
    right = PromptZones({"identity": "agent", "policy": "safe"})
    assert left.prefix_bytes == right.prefix_bytes
    assert left.receipt()["prefix_bytes"] == len(left.prefix_bytes)


def test_invalidation_is_typed_and_increments_once_per_event():
    zones = PromptZones({"identity": "agent"})
    assert zones.generation == 0
    assert zones.invalidate(InvalidationReason.TOOL_REGISTRY) == 1
    assert zones.invalidate(InvalidationReason.TOOL_REGISTRY) == 2
    assert zones.receipt()["last_invalidation"] == "tool_registry"


def test_unknown_invalidation_reason_is_rejected():
    zones = PromptZones({"identity": "agent"})
    try:
        zones.invalidate("tool_registry")
    except TypeError:
        pass
    else:
        raise AssertionError("string reasons must not bypass the typed contract")


def test_lease_reuses_affinity_and_releases_on_finish():
    runtime = FakeRuntime()
    lease = InferenceLease("session-1", PromptZones({"identity": "agent"}), runtime)
    first = lease.acquire()
    assert lease.acquire() == first
    assert len(runtime.acquires) == 1
    lease.finish()
    lease.finish()
    assert runtime.releases == ["opaque-1"]
    assert "slot_id" not in first.to_dict()


def test_lease_refreshes_after_prefix_invalidation_and_context_releases():
    runtime = FakeRuntime()
    zones = PromptZones({"identity": "agent"})
    lease = InferenceLease("session-1", zones, runtime)
    with lease as active:
        assert active.receipt is not None
    assert runtime.releases == ["opaque-1"]
    zones.invalidate(InvalidationReason.MODEL_SWAP)
    refreshed = lease.acquire()
    assert refreshed.generation == 1
    assert len(runtime.acquires) == 2
    lease.cancel()
    assert runtime.releases == ["opaque-1", "opaque-2"]
