from __future__ import annotations

import json
import unittest
from dataclasses import replace
from pathlib import Path

from agent.mapper_adapter import (
    AdapterStatus,
    CachePolicy,
    CausalScope,
    MapperCapabilities,
    MapperClient,
    MapperResult,
    SnapshotRequest,
)


def _snapshot(*, revision: str = "r1", snapshot_id: str = "snapshot-1") -> dict:
    return {
        "schema": "simplicio.context-snapshot/v1",
        "schema_version": "v1",
        "repository_id": "repo",
        "revision": revision,
        "root_hash": "root-hash",
        "build_config_hash": "",
        "producer": {
            "name": "simplicio-mapper",
            "version": "0.24.1",
            "artifact_version": 1,
        },
        "snapshot_id": snapshot_id,
        "generated_at": "2026-01-01T00:00:00Z",
        "source_set": ["src/app.py"],
        "fidelity": {"status": "complete", "gate": "ready", "omissions": []},
        "task": {"omissions": []},
        "graph": {
            "nodes": [
                {
                    "id": "file:src/app.py",
                    "scale": "meso",
                    "source": {"file": "src/app.py"},
                }
            ],
            "edges": [],
        },
    }


class FakeTransport:
    def __init__(
        self, payload: dict, *, status: AdapterStatus = AdapterStatus.AVAILABLE
    ):
        self.payload = payload
        self.status = status
        self.calls = 0

    def capabilities(self) -> MapperCapabilities:
        return MapperCapabilities(
            transport="fake",
            producer="simplicio-mapper",
            producer_version="0.24.1",
            schema_ids=("simplicio.context-snapshot/v1", "simplicio.context-graph/v1"),
            contract_manifest_digest="sha256:manifest",
        )

    def create_or_resolve_snapshot(
        self, request: SnapshotRequest
    ) -> MapperResult[dict]:
        self.calls += 1
        if self.status is not AdapterStatus.AVAILABLE:
            return MapperResult.failure(
                self.status, "MAPPER_UNAVAILABLE", "fake transport unavailable"
            )
        return MapperResult.success(self.payload)

    def refresh(self, request: SnapshotRequest) -> MapperResult[dict]:
        return self.create_or_resolve_snapshot(request)


def _validator(payload: dict, **_: object) -> dict:
    return {
        "schema": "simplicio.context-conformance-report/v1",
        "target_schema": payload.get("schema", ""),
        "valid": True,
        "reason_codes": [],
        "snapshot_id": payload.get("snapshot_id", ""),
    }


def _request(revision: str = "r1", *, attempt_id: str = "a1") -> SnapshotRequest:
    return SnapshotRequest(
        root=Path("/repo"),
        repository_id="repo",
        profile="default",
        revision=revision,
        causal_scope=CausalScope(session_id="s1", turn_id="t1", attempt_id=attempt_id),
    )


class MapperAdapterTest(unittest.TestCase):
    def test_snapshot_is_validated_pinned_and_expanded_by_handle(self) -> None:
        transport = FakeTransport(_snapshot())
        client = MapperClient(transport, validator=_validator)

        result = client.create_or_resolve_snapshot(_request())

        self.assertIs(result.status, AdapterStatus.AVAILABLE)
        self.assertIsNotNone(result.value)
        self.assertEqual(result.value.snapshot_id, "snapshot-1")
        source = client.resolve_source_handle(result.value, {"file": "src/app.py"})
        self.assertIs(source.status, AdapterStatus.AVAILABLE)
        self.assertEqual(source.value, {"file": "src/app.py"})
        expanded = client.expand_context(
            result.value, handles=("file:src/app.py",), budget_nodes=1
        )
        self.assertIs(expanded.status, AdapterStatus.AVAILABLE)
        self.assertIsNotNone(expanded.value)
        self.assertEqual(expanded.value.nodes[0]["id"], "file:src/app.py")
        self.assertEqual(expanded.metrics.materialized_nodes, 1)

    def test_same_attempt_cannot_switch_revision_silently(self) -> None:
        transport = FakeTransport(_snapshot())
        client = MapperClient(transport, validator=_validator)
        first = client.create_or_resolve_snapshot(_request("r1"))
        transport.payload = _snapshot(revision="r2", snapshot_id="snapshot-2")

        second = client.refresh(_request("r2"))

        self.assertIs(first.status, AdapterStatus.AVAILABLE)
        self.assertIs(second.status, AdapterStatus.STALE)
        self.assertEqual(second.reason_code, "PIN_REVISION_CHANGED")
        self.assertEqual(transport.calls, 2)

    def test_cache_is_bounded_and_isolated_by_repo_profile_revision(self) -> None:
        first = _snapshot(snapshot_id="a")
        second = _snapshot(snapshot_id="b", revision="r2")
        transport = FakeTransport(first)
        client = MapperClient(
            transport,
            validator=_validator,
            cache_policy=CachePolicy(max_entries=1, max_bytes=100_000),
        )

        self.assertIs(
            client.create_or_resolve_snapshot(_request("r1", attempt_id="a1")).status,
            AdapterStatus.AVAILABLE,
        )
        transport.payload = second
        self.assertIs(
            client.create_or_resolve_snapshot(_request("r2", attempt_id="a2")).status,
            AdapterStatus.AVAILABLE,
        )
        self.assertEqual(client.cache_stats().entries, 1)

        transport.payload = first
        isolated = client.create_or_resolve_snapshot(
            replace(_request("r1", attempt_id="a3"), profile="other")
        )
        self.assertIs(isolated.status, AdapterStatus.AVAILABLE)
        self.assertEqual(transport.calls, 3)

    def test_tampered_payload_is_typed_and_has_no_fallback(self) -> None:
        def tamper_validator(payload: dict, **_: object) -> dict:
            return {
                "schema": "simplicio.context-conformance-report/v1",
                "target_schema": payload.get("schema", ""),
                "valid": False,
                "reason_codes": [
                    {
                        "code": "SNAPSHOT_HASH_MISMATCH",
                        "path": "$.snapshot_id",
                        "message": "mismatch",
                    }
                ],
                "snapshot_id": payload.get("snapshot_id", ""),
            }

        client = MapperClient(FakeTransport(_snapshot()), validator=tamper_validator)

        result = client.create_or_resolve_snapshot(_request())

        self.assertIs(result.status, AdapterStatus.TAMPERED)
        self.assertEqual(result.reason_code, "SNAPSHOT_HASH_MISMATCH")
        self.assertIsNone(result.value)

    def test_unavailable_binding_is_explicit_without_fallback(self) -> None:
        class UnavailableTransport(FakeTransport):
            def capabilities(self) -> MapperCapabilities:
                return MapperCapabilities(
                    transport="binding",
                    producer="simplicio-mapper",
                    producer_version="",
                    schema_ids=(),
                    contract_manifest_digest="",
                    available=False,
                    reason="package missing",
                )

        result = MapperClient(
            UnavailableTransport(_snapshot())
        ).create_or_resolve_snapshot(_request())

        self.assertIs(result.status, AdapterStatus.UNAVAILABLE)
        self.assertEqual(result.reason_code, "MAPPER_UNAVAILABLE")

    def test_events_are_causal_and_redacted(self) -> None:
        events: list[dict] = []
        client = MapperClient(
            FakeTransport(_snapshot()), validator=_validator, event_sink=events.append
        )

        result = client.create_or_resolve_snapshot(_request())

        self.assertIs(result.status, AdapterStatus.AVAILABLE)
        self.assertEqual(events[0]["schema"], "simplicio.mapper-adapter-event/v1")
        self.assertEqual(events[0]["attempt_id"], "a1")
        self.assertNotIn("/repo", json.dumps(events))
        self.assertNotIn("app.py", json.dumps(events))

    def test_contract_manifest_digest_can_be_pinned(self) -> None:
        client = MapperClient(
            FakeTransport(_snapshot()),
            validator=_validator,
            expected_contract_manifest_digest="sha256:expected",
        )

        result = client.create_or_resolve_snapshot(_request())

        self.assertIs(result.status, AdapterStatus.INCOMPATIBLE_SCHEMA)
        self.assertEqual(result.reason_code, "CONTRACT_MANIFEST_DIGEST_MISMATCH")

    def test_freshness_budget_returns_stale(self) -> None:
        transport = FakeTransport(_snapshot())
        client = MapperClient(transport, validator=_validator)

        result = client.create_or_resolve_snapshot(
            replace(_request(), max_age_seconds=1)
        )

        self.assertIs(result.status, AdapterStatus.STALE)
        self.assertEqual(result.reason_code, "SNAPSHOT_EXPIRED")

    def test_mapper_fixture_is_consumed_from_installed_package_when_available(
        self,
    ) -> None:
        try:
            import importlib.resources
            import simplicio_mapper as mapper
        except ImportError:
            self.skipTest("simplicio-mapper is not installed")

        fixture = (
            importlib.resources.files(mapper)
            / "contracts/context-snapshot/v1/fixtures/minimum/context-snapshot.json"
        )
        if not fixture.is_file():
            self.skipTest(
                "installed Mapper does not expose the packaged conformance fixture"
            )
        payload = json.loads(fixture.read_text(encoding="utf-8"))
        from simplicio_mapper.context_contract import validate_context_payload

        report = validate_context_payload(payload)
        self.assertIs(report["valid"], True)
        self.assertEqual(report["target_schema"], "simplicio.context-snapshot/v1")

        invalid = (
            importlib.resources.files(mapper)
            / "contracts/context-snapshot/v1/fixtures/invalid/hash-mismatch/context-snapshot.json"
        )
        if invalid.is_file():
            negative = validate_context_payload(
                json.loads(invalid.read_text(encoding="utf-8"))
            )
            self.assertIs(negative["valid"], False)
            self.assertIn(
                "SNAPSHOT_HASH_MISMATCH",
                {item["code"] for item in negative["reason_codes"]},
            )
