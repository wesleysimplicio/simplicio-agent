"""
HBI — Hermes Binary Interface (Python)

Pure-Python implementation of the Asolaria HBI/HBP wire format, matching the
`asolaria_hbi_hbp` Rust crate. Zero external dependencies (stdlib only).

HBP: hash-chain verified binary protocol rows (pipe-delimited, no JSON)
HBI: byte-offset index sidecar (.hbi files)
Receipts: tamper-evident hash chain

Wire format (from the Rust crate):
  HBP row:  TAG|k=v|...|json=0
  HBI row:  IDX|pid=..|off=..|len=..|json=0
  Receipt:  row|prev_event_hash=..|event_hash=..
  AGT:      AGT-<sha16> (20 chars)

Usage:
    from hbi import encode_row, parse_row, ReceiptChain, IdxPointer

    # Encode a HBP row
    row = encode_row("EVIDENCE", [("action", "gate"), ("status", "pass")])
    assert row == "EVIDENCE|action=gate|status=pass|json=0"

    # Hash chain
    chain = ReceiptChain()
    r1 = chain.append("EVIDENCE|action=gate|status=pass|json=0")
    r2 = chain.append("EVIDENCE|action=checkpoint|status=ok|json=0")
    assert chain.verify([r1, r2])
"""

from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from typing import TYPE_CHECKING

# ---------------------------------------------------------------------------
# SHA256
# ---------------------------------------------------------------------------

def sha256_hex(data: bytes) -> str:
    """Lowercase hex SHA-256 (64 chars)."""
    return hashlib.sha256(data).hexdigest()


def sha256_digest(data: bytes) -> bytes:
    """Raw SHA-256 digest (32 bytes)."""
    return hashlib.sha256(data).digest()


def agt(content: bytes) -> str:
    """Content address: AGT- + first 16 hex chars of SHA-256."""
    return "AGT-" + sha256_hex(content)[:16]


# ---------------------------------------------------------------------------
# HBP row encoding/decoding
# ---------------------------------------------------------------------------

def _esc(v: str) -> str:
    """Escape a value for HBP pipe-delimited format."""
    return v.replace("\\", "\\\\").replace("|", "\\p").replace("\n", "\\n")


def _unesc(v: str) -> str:
    """Unescape a HBP value."""
    out: List[str] = []
    i = 0
    while i < len(v):
        c = v[i]
        if c == "\\" and i + 1 < len(v):
            n = v[i + 1]
            if n == "\\":
                out.append("\\")
            elif n == "p":
                out.append("|")
            elif n == "n":
                out.append("\n")
            else:
                out.append("\\")
                out.append(n)
            i += 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


def encode_row(tag: str, fields: List[Tuple[str, str]]) -> str:
    """Encode one HBP row: TAG|k=v|...|json=0.

    Args:
        tag: Row tag (e.g. "EVIDENCE", "CHECKPOINT", "DECISION")
        fields: List of (key, value) pairs

    Returns:
        Encoded row string with trailing `|json=0` marker
    """
    parts = [tag]
    for k, v in fields:
        parts.append(f"{k}={_esc(v)}")
    parts.append("json=0")
    return "|".join(parts)


def parse_row(row: str) -> Tuple[str, List[Tuple[str, str]]]:
    """Parse a HBP row back into (tag, fields).

    Args:
        row: Encoded row string

    Returns:
        Tuple of (tag, list of (key, value) pairs)
    """
    if not row:
        return ("", [])

    parts: List[str] = []
    cur: List[str] = []
    i = 0
    while i < len(row):
        c = row[i]
        if c == "\\":
            cur.append("\\")
            if i + 1 < len(row):
                cur.append(row[i + 1])
                i += 1
        elif c == "|":
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(c)
        i += 1
    parts.append("".join(cur))

    if not parts:
        return ("", [])

    tag = parts[0]
    fields: List[Tuple[str, str]] = []
    for p in parts[1:]:
        eq_pos = p.find("=")
        if eq_pos >= 0:
            fields.append((p[:eq_pos], _unesc(p[eq_pos + 1:])))
        elif p:
            fields.append((p, ""))
    return (tag, fields)


# ---------------------------------------------------------------------------
# HBI index pointer
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class IdxPointer:
    """A byte-offset pointer into a .hbp blob (the .hbi sidecar row shape)."""

    pid: str     # Pointer ID (content address or seq)
    off: int     # Byte offset into the HBP blob
    size: int    # Length of the pointed-to data

    def encode(self) -> str:
        """Encode as a HBI row: IDX|pid=..|off=..|len=..|json=0"""
        return encode_row("IDX", [
            ("pid", self.pid),
            ("off", str(self.off)),
            ("len", str(self.size)),
        ])

    @classmethod
    def from_row(cls, row: str) -> IdxPointer:
        """Parse a HBI index pointer from a row."""
        tag, fields = parse_row(row)
        assert tag == "IDX", f"Expected IDX tag, got {tag}"
        d = dict(fields)
        return cls(
            pid=d.get("pid", ""),
            off=int(d.get("off", "0")),
            size=int(d.get("len", "0")),
        )


# ---------------------------------------------------------------------------
# HBI file read/write
# ---------------------------------------------------------------------------


def read_hbi(path: Path) -> List[IdxPointer]:
    """Read a .hbi sidecar file, returning list of index pointers.

    .hbi files contain one HBI row per line, each ending with |json=0.
    """
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    pointers: List[IdxPointer] = []
    for line in text.strip().split("\n"):
        line = line.strip()
        if line:
            pointers.append(IdxPointer.from_row(line))
    return pointers


def write_hbi(path: Path, pointers: List[IdxPointer]) -> None:
    """Write a .hbi sidecar file."""
    if path.parent:
        path.parent.mkdir(parents=True, exist_ok=True)
    lines = "\n".join(p.encode() for p in pointers)
    path.write_text(lines + "\n" if lines else "", encoding="utf-8")


def read_hbp(path: Path) -> List[str]:
    """Read a .hbp chain file, returning list of receipt rows.

    .hbp files contain one HBP receipt row per line.
    """
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    return [line.strip() for line in text.strip().split("\n") if line.strip()]


def write_hbp(path: Path, rows: List[str]) -> None:
    """Write a .hbp chain file."""
    if path.parent:
        path.parent.mkdir(parents=True, exist_ok=True)
    lines = "\n".join(rows)
    path.write_text(lines + "\n" if lines else "", encoding="utf-8")


# ---------------------------------------------------------------------------
# Receipt chain — tamper-evident hash chain
# ---------------------------------------------------------------------------

GENESIS: str = "0000000000000000000000000000000000000000000000000000000000000000"


class ReceiptChain:
    """An append-only, tamper-evident receipt chain over HBP rows.

    Each receipt includes the previous row's hash, forming a chain.
    Tampering with any earlier row changes every subsequent hash.

    Usage:
        chain = ReceiptChain()
        r1 = chain.append("EVIDENCE|action=gate|status=pass|json=0")
        r2 = chain.append("EVIDENCE|action=decision|status=approve|json=0")
        assert ReceiptChain.verify_static([r1, r2])
    """

    def __init__(self, prev: Optional[str] = None) -> None:
        self._prev = prev or GENESIS

    def append(self, row: str) -> str:
        """Seal `row` into a receipt.

        Returns the full receipt row with prev_event_hash and event_hash.
        """
        body = f"{row}|prev_event_hash={self._prev}"
        eh = sha256_hex(body.encode("utf-8"))
        self._prev = eh
        return f"{body}|event_hash={eh}"

    def head(self) -> str:
        """The current chain head (last event_hash)."""
        return self._prev

    @classmethod
    def verify_static(cls, receipts: List[str]) -> bool:
        """Verify a full chain of receipt rows.

        Each event_hash must equal SHA-256 of everything before it,
        and each prev_event_hash must equal the previous row's event_hash.
        """
        prev = GENESIS
        for r in receipts:
            marker = "|event_hash="
            pos = r.rfind(marker)
            if pos < 0:
                return False
            body = r[:pos]
            claimed = r[pos + len(marker):]
            if sha256_hex(body.encode("utf-8")) != claimed:
                return False
            pm = "|prev_event_hash="
            pp = body.rfind(pm)
            if pp < 0:
                return False
            if body[pp + len(pm):] != prev:
                return False
            prev = claimed
        return True


# ---------------------------------------------------------------------------
# File-based HBP ledger
# ---------------------------------------------------------------------------


class HbpLedger:
    """A file-backed HBP evidence ledger with automatic hash chaining.

    Manages a .hbp chain file and a .hbi index file, providing
    append-only logging with integrity verification.

    Usage:
        ledger = HbpLedger(Path("~/.simplicio/evidence/run-001.hbp"))
        ledger.append("GATE", [("action", "check"), ("result", "pass")])

        # Read back
        for (seq, row) in ledger.rows():
            tag, fields = parse_row(row)
            print(f"{seq}: {tag}")
    """

    def __init__(self, path: Path) -> None:
        self.path = path.with_suffix(".hbp")
        self.hbi_path = path.with_suffix(".hbi")
        self._chain = ReceiptChain()
        self._rows: List[str] = []
        self._pointers: List[IdxPointer] = []
        self._load()

    def _load(self) -> None:
        """Load existing chain from disk."""
        rows = read_hbp(self.path)
        if rows:
            for row in rows:
                self._rows.append(row)
            # Get the last event_hash as the chain head
            marker = "|event_hash="
            last_row = rows[-1]
            pos = last_row.rfind(marker)
            if pos >= 0:
                self._chain._prev = last_row[pos + len(marker):]
            # Rebuild pointers
            offset = 0
            for i, row in enumerate(rows):
                self._pointers.append(IdxPointer(
                    pid=f"seq-{i}",
                    off=offset,
                    size=len(row.encode("utf-8")),
                ))
                offset += len(row.encode("utf-8")) + 1  # +1 for newline

    def append(self, tag: str, fields: List[Tuple[str, str]]) -> str:
        """Append a HBP row to the ledger with hash chain sealing.

        Args:
            tag: Row tag
            fields: Key-value fields

        Returns:
            The sealed receipt row
        """
        row = encode_row(tag, fields)
        receipt = self._chain.append(row)
        self._rows.append(receipt)

        # Update pointer
        offset = sum(len(r.encode("utf-8")) + 1 for r in self._rows[:-1])
        self._pointers.append(IdxPointer(
            pid=f"seq-{len(self._rows) - 1}",
            off=offset,
            size=len(receipt.encode("utf-8")),
        ))

        return receipt

    def flush(self) -> None:
        """Write chain and index to disk."""
        write_hbp(self.path, self._rows)
        write_hbi(self.hbi_path, self._pointers)

    def verify(self) -> bool:
        """Verify the entire chain integrity."""
        return ReceiptChain.verify_static(self._rows)

    def rows(self) -> List[Tuple[int, str]]:
        """Return all rows as (seq, receipt) pairs."""
        return [(i, r) for i, r in enumerate(self._rows)]

    def head(self) -> str:
        """Current chain head hash."""
        return self._chain.head()

    def __len__(self) -> int:
        return len(self._rows)


# ---------------------------------------------------------------------------
# HBP binary serialization (for struct data, not text)
# ---------------------------------------------------------------------------


def pack_binary(values: Dict[str, Any]) -> bytes:
    """Pack a dict of values into a compact binary format.

    Uses HBP row encoding for the metadata, then struct for numeric data.
    This is the Python-side equivalent of bincode serialization.

    Format:
        [n_fields: u32 LE][field_1..field_N][payload: bytes]

    Each field:
        [key_len: u16 LE][key: utf8][val_len: u32 LE][val: utf8]
    """
    # Encode fields as HBP-style key=value pairs
    fields = []
    payload = b""
    for k, v in values.items():
        if isinstance(v, bool):
            fields.append(encode_row("VAL", [("k", k), ("t", "bool"), ("v", "1" if v else "0")]))
        elif isinstance(v, (int, float)):
            fields.append(encode_row("VAL", [("k", k), ("t", type(v).__name__), ("v", str(v))]))
        elif isinstance(v, str):
            fields.append(encode_row("VAL", [("k", k), ("t", "str"), ("v", v)]))
        elif isinstance(v, bytes):
            payload += struct.pack("<I", len(v)) + v
            fields.append(encode_row("VAL", [("k", k), ("t", "bytes"), ("v", str(len(v)))]))
        elif isinstance(v, bool):
            fields.append(encode_row("VAL", [("k", k), ("t", "bool"), ("v", "1" if v else "0")]))
        elif v is None:
            fields.append(encode_row("VAL", [("k", k), ("t", "none"), ("v", "")]))
        elif isinstance(v, (list, dict)):
            import json
            json_str = json.dumps(v, separators=(",", ":"), ensure_ascii=False)
            fields.append(encode_row("VAL", [("k", k), ("t", "json"), ("v", json_str)]))
        else:
            fields.append(encode_row("VAL", [("k", k), ("t", type(v).__name__), ("v", str(v))]))

    fields_text = "\n".join(fields).encode("utf-8")
    header = struct.pack("<I", len(fields)) + struct.pack("<I", len(fields_text))
    return header + fields_text + payload


def unpack_binary(data: bytes) -> Dict[str, Any]:
    """Unpack binary data back into a dict.

    Reverse of pack_binary.
    """
    if len(data) < 8:
        return {}
    n_fields = struct.unpack("<I", data[:4])[0]
    fields_len = struct.unpack("<I", data[4:8])[0]
    pos = 8

    fields_text = data[pos:pos + fields_len].decode("utf-8")
    pos += fields_len

    result: Dict[str, Any] = {}
    for line in fields_text.strip().split("\n"):
        if not line.strip():
            continue
        tag, kv = parse_row(line)
        if tag != "VAL":
            continue
        d = dict(kv)
        k = d.get("k", "")
        t = d.get("t", "")
        v = d.get("v", "")
        if t == "bool":
            result[k] = v == "1"
        elif t == "int":
            result[k] = int(v)
        elif t == "float":
            result[k] = float(v)
        elif t == "str":
            result[k] = v
        elif t == "bool":
            result[k] = v == "1"
        elif t == "none":
            result[k] = None
        elif t == "bytes":
            blen = int(v)
            pos += 4  # skip length prefix that pack_binary prepended
            result[k] = data[pos:pos + blen]
            pos += blen
        elif t == "json":
            import json
            result[k] = json.loads(v)
        else:
            result[k] = v

    return result