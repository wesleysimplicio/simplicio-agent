"""Fixture-driven identity contract for the bounded GitHub #191 slice."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import hermes_cli

from agent.telemetry.receipts import content_hash, lookup_receipt, record_receipt


FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "machine-contracts"
    / "mcp-receipt-identity.json"
)


def _contract() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_mcp_server_info_and_receipt_share_canonical_product_version(
    monkeypatch, tmp_path: Path
) -> None:
    from agent.transports import hermes_tools_mcp_server as server_module

    contract = _contract()
    captured = {}

    class FakeFastMCP:
        def __init__(self, name, **kwargs):
            captured["name"] = name
            self._mcp_server = SimpleNamespace(version=None)

        def add_tool(self, *args, **kwargs):
            return None

    fake_fastmcp = ModuleType("mcp.server.fastmcp")
    fake_fastmcp.FastMCP = FakeFastMCP
    monkeypatch.setitem(sys.modules, "mcp.server.fastmcp", fake_fastmcp)
    monkeypatch.setattr("model_tools.get_tool_definitions", lambda quiet_mode=True: [])

    server = server_module._build_server()
    receipt = record_receipt(payload="issue-191", directory=tmp_path)
    persisted = json.loads(
        (tmp_path / f"{receipt.sha}.json").read_text(encoding="utf-8")
    )

    assert captured["name"] == contract["mcp"]["server_info_name"]
    assert server._mcp_server.version == hermes_cli.__version__
    assert server_module.LEGACY_MCP_SERVER_NAME in contract["mcp"][
        "legacy_server_names"
    ]
    assert persisted["schema"] == contract["receipt"]["schema"]
    assert persisted["producer"] == {
        "product": contract["receipt"]["product"],
        "component": contract["receipt"]["component"],
        "version": hermes_cli.__version__,
    }


def test_unversioned_receipt_is_upcast_in_memory_without_rewrite(tmp_path: Path) -> None:
    contract = _contract()
    payload = "pre-schema receipt"
    sha = content_hash(payload)
    path = tmp_path / f"{sha}.json"
    legacy = {
        "sha": sha,
        "yool_id": "agent.ops.legacy",
        "lane": "fast",
        "status": "ok",
        "cost": {"tokens": 1, "tokens_raw": 1, "tokens_saved": 0},
        "ts": "2026-07-13T00:00:00Z",
        "meta": {},
    }
    path.write_text(json.dumps(legacy), encoding="utf-8")

    receipt = lookup_receipt(payload, tmp_path)

    assert receipt is not None
    assert receipt.schema == contract["receipt"]["schema"]
    assert receipt.producer.product == contract["receipt"]["product"]
    assert receipt.producer.component == contract["receipt"]["component"]
    assert receipt.producer.version == "unknown"
    assert receipt.legacy_source_schema == contract["receipt"][
        "legacy_source_schema"
    ]
    assert json.loads(path.read_text(encoding="utf-8")) == legacy
