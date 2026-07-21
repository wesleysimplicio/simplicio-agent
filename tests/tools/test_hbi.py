"""Tests for HBI (Hermes Binary Interface) Python module."""

import json
import struct
import tempfile
from pathlib import Path

from tools.hbi import (
    GENESIS,
    HbpLedger,
    IdxPointer,
    ReceiptChain,
    agt,
    encode_row,
    pack_binary,
    parse_row,
    read_hbi,
    read_hbp,
    sha256_hex,
    unpack_binary,
    write_hbi,
    write_hbp,
)


# ---------------------------------------------------------------------------
# HBP row encoding/decoding
# ---------------------------------------------------------------------------

class TestHbpRow:
    def test_encode_basic(self):
        row = encode_row("EVIDENCE", [("action", "gate"), ("status", "pass")])
        assert row == "EVIDENCE|action=gate|status=pass|json=0"

    def test_parse_basic(self):
        row = "EVIDENCE|action=gate|status=pass|json=0"
        tag, fields = parse_row(row)
        assert tag == "EVIDENCE"
        assert ("action", "gate") in fields
        assert ("status", "pass") in fields
        assert ("json", "0") in fields

    def test_escape_pipe(self):
        row = encode_row("TEST", [("value", "a|b")])
        assert "\\p" in row
        tag, fields = parse_row(row)
        assert ("value", "a|b") in fields

    def test_escape_newline(self):
        val = "line1\nline2"
        row = encode_row("TEST", [("v", val)])
        assert "\\n" in row
        tag, fields = parse_row(row)
        assert ("v", val) in fields

    def test_escape_backslash(self):
        row = encode_row("TEST", [("v", "a\\b")])
        tag, fields = parse_row(row)
        assert ("v", "a\\b") in fields

    def test_empty_row(self):
        tag, fields = parse_row("")
        assert tag == ""
        assert fields == []

    def test_single_tag(self):
        tag, fields = parse_row("HELLO|json=0")
        assert tag == "HELLO"
        assert ("json", "0") in fields


# ---------------------------------------------------------------------------
# SHA256 / AGT
# ---------------------------------------------------------------------------

class TestHashing:
    def test_sha256_hex(self):
        h = sha256_hex(b"hello")
        assert len(h) == 64
        assert h == "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"

    def test_agt(self):
        addr = agt(b"test")
        assert addr.startswith("AGT-")
        assert len(addr) == 20


# ---------------------------------------------------------------------------
# Receipt chain
# ---------------------------------------------------------------------------

class TestReceiptChain:
    def test_chain_verify(self):
        chain = ReceiptChain()
        r1 = chain.append("EVIDENCE|action=gate|status=pass|json=0")
        r2 = chain.append("EVIDENCE|action=decision|status=approve|json=0")
        assert ReceiptChain.verify_static([r1, r2])

    def test_chain_tamper(self):
        chain = ReceiptChain()
        r1 = chain.append("EVIDENCE|action=gate|status=pass|json=0")
        r2 = chain.append("EVIDENCE|action=decision|status=approve|json=0")
        r3 = r2.replace("approve", "reject")
        assert not ReceiptChain.verify_static([r1, r3])

    def test_chain_single(self):
        chain = ReceiptChain()
        r1 = chain.append("EVIDENCE|action=gate|status=pass|json=0")
        assert ReceiptChain.verify_static([r1])

    def test_chain_head(self):
        chain = ReceiptChain()
        assert chain.head() == GENESIS
        chain.append("EVIDENCE|action=gate|status=pass|json=0")
        assert chain.head() != GENESIS
        assert len(chain.head()) == 64


# ---------------------------------------------------------------------------
# HBI index pointer
# ---------------------------------------------------------------------------

class TestIdxPointer:
    def test_encode_decode(self):
        ptr = IdxPointer(pid="seq-0", off=0, size=100)
        row = ptr.encode()
        parsed = IdxPointer.from_row(row)
        assert parsed == ptr

    def test_from_row(self):
        ptr = IdxPointer.from_row("IDX|pid=seq-0|off=42|len=100|json=0")
        assert ptr.pid == "seq-0"
        assert ptr.off == 42
        assert ptr.size == 100


# ---------------------------------------------------------------------------
# HBI file I/O
# ---------------------------------------------------------------------------

class TestHbiFile:
    def test_write_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "index.hbi"
            pointers = [
                IdxPointer(pid="seq-0", off=0, size=50),
                IdxPointer(pid="seq-1", off=50, size=100),
            ]
            write_hbi(path, pointers)
            loaded = read_hbi(path)
            assert loaded == pointers

    def test_read_nonexistent(self):
        loaded = read_hbi(Path("/nonexistent/file.hbi"))
        assert loaded == []


class TestHbpFile:
    def test_write_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "chain.hbp"
            rows = [
                "EVIDENCE|action=gate|status=pass|json=0|prev_event_hash=0000|event_hash=abcd",
                "EVIDENCE|action=checkpoint|status=ok|json=0|prev_event_hash=abcd|event_hash=ef01",
            ]
            write_hbp(path, rows)
            loaded = read_hbp(path)
            assert loaded == rows

    def test_read_nonexistent(self):
        loaded = read_hbp(Path("/nonexistent/file.hbp"))
        assert loaded == []


# ---------------------------------------------------------------------------
# HBP ledger
# ---------------------------------------------------------------------------

class TestHbpLedger:
    def test_append_and_verify(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = HbpLedger(Path(tmp) / "run-001")
            ledger.append("GATE", [("action", "check"), ("result", "pass")])
            ledger.append("GATE", [("action", "decision"), ("result", "approve")])
            ledger.flush()
            assert ledger.verify()
            assert len(ledger) == 2

    def test_persistence(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "run-002"
            ledger = HbpLedger(path)
            ledger.append("GATE", [("action", "check"), ("result", "pass")])
            ledger.flush()

            ledger2 = HbpLedger(path)
            assert ledger2.verify()
            assert len(ledger2) == 1
            assert ledger2.head() == ledger.head()

    def test_empty_ledger(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = HbpLedger(Path(tmp) / "empty")
            assert ledger.verify()
            assert len(ledger) == 0

    def test_multiple_batches(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "batch"
            ledger = HbpLedger(path)
            for i in range(10):
                ledger.append("BATCH", [("seq", str(i)), ("value", f"v{i}")])
            ledger.flush()
            assert ledger.verify()
            assert len(ledger) == 10

    def test_hbi_sidecar(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sidecar"
            ledger = HbpLedger(path)
            ledger.append("GATE", [("action", "check"), ("result", "pass")])
            ledger.flush()
            assert path.with_suffix(".hbi").exists()
            pointers = read_hbi(path.with_suffix(".hbi"))
            assert len(pointers) == 1
            assert pointers[0].pid == "seq-0"


# ---------------------------------------------------------------------------
# Binary serialization
# ---------------------------------------------------------------------------

class TestBinarySerialization:
    def test_pack_unpack(self):
        data = pack_binary({"name": "test", "count": 42, "active": True})
        result = unpack_binary(data)
        assert result["name"] == "test"
        assert result["count"] == 42
        assert result["active"] is True

    def test_float(self):
        data = pack_binary({"pi": 3.14159})
        result = unpack_binary(data)
        assert abs(result["pi"] - 3.14159) < 0.001

    def test_bool_false(self):
        data = pack_binary({"flag": False})
        result = unpack_binary(data)
        assert result["flag"] is False

    def test_none(self):
        data = pack_binary({"value": None})
        result = unpack_binary(data)
        assert result["value"] is None

    def test_bytes(self):
        data = pack_binary({"raw": b"\x00\x01\x02"})
        result = unpack_binary(data)
        assert result["raw"] == b"\x00\x01\x02"

    def test_json_value(self):
        data = pack_binary({"items": [1, 2, 3], "nested": {"a": 1}})
        result = unpack_binary(data)
        assert result["items"] == [1, 2, 3]
        assert result["nested"] == {"a": 1}

    def test_empty(self):
        data = pack_binary({})
        result = unpack_binary(data)
        assert result == {}

    def test_mixed(self):
        data = pack_binary({
            "name": "test",
            "count": 42,
            "active": True,
            "factor": 3.14,
            "data": None,
            "tags": ["a", "b"],
        })
        result = unpack_binary(data)
        assert result["name"] == "test"
        assert result["count"] == 42
        assert result["active"] is True
        assert abs(result["factor"] - 3.14) < 0.001
        assert result["data"] is None
        assert result["tags"] == ["a", "b"]