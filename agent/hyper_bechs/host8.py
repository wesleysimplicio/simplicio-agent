"""HYPER-BECHS — Host-8 binary protocol implementation.

Host-8 binary format:
  Header: 8 bytes
    - magic:   2 bytes  (b'H8')
    - version: 1 byte   (currently 0x01)
    - type:    1 byte   (MSG_TYPE_*)
    - length:  4 bytes  (uint32, big-endian, body length in bytes)
  Body: <length> bytes (raw binary or JSON-encoded, depending on json=0 flag)

Flags (in type byte):
  bit 7 (0x80): json=0 — binary-pure mode (no JSON encoding)
  bits 0-6: message type id

Omniquant: run-length encoding for repeated byte sequences.
  Format: sequence of (marker, count, byte) triplets for runs of length >= 4,
  or raw bytes for shorter runs.
  Marker byte: 0xFE (escape). If the raw stream contains 0xFE, it is escaped
  as 0xFE 0x00 0x01 (count=0 sentinel meaning "literal 0xFE, not a run").
"""

from __future__ import annotations

import json
import struct
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAGIC = b"H8"
VERSION = 0x01

# Type IDs (bits 0-6 of the type byte)
MSG_TYPE_DATA = 0x01
MSG_TYPE_CONTROL = 0x02
MSG_TYPE_ACK = 0x03
MSG_TYPE_ERROR = 0x04

# Flag bits in type byte
FLAG_JSON_ZERO = 0x80  # json=0: binary-pure mode (no JSON encoding)

# Omniquant marker
_OQ_MARKER = 0xFE
_OQ_MIN_RUN = 4  # minimum run length to compress


# ---------------------------------------------------------------------------
# Message dataclass
# ---------------------------------------------------------------------------


@dataclass
class Host8Message:
    """Represents a Host-8 protocol message.

    Attributes:
        msg_type:  Message type id (bits 0-6). One of MSG_TYPE_*.
        payload:   Message payload (bytes in binary mode, any in JSON mode).
        json_zero: If True, encode/decode payload as raw bytes (json=0 flag).
        use_omniquant: If True, apply Omniquant compression to the body.
    """

    msg_type: int = MSG_TYPE_DATA
    payload: Any = b""
    json_zero: bool = False
    use_omniquant: bool = False

    # Internal: raw body bytes after serialisation (set by encode/decode)
    _raw_body: bytes = field(default=b"", init=False, repr=False, compare=False)


# ---------------------------------------------------------------------------
# Omniquant — simple run-length compression
# ---------------------------------------------------------------------------


def omniquant_compress(data: bytes) -> bytes:
    """Compress *data* using Omniquant run-length encoding.

    Runs of >= 4 identical bytes are encoded as:
      0xFE  <count: 1 byte, 1-255>  <byte>

    A literal 0xFE in the stream that is NOT part of a run is escaped as:
      0xFE  0x00  0xFE

    Runs longer than 255 bytes are split into multiple triplets.
    """
    if not data:
        return b""

    out: list[int] = []
    i = 0
    n = len(data)

    while i < n:
        b = data[i]
        # Count run length
        run = 1
        while i + run < n and data[i + run] == b and run < 255:
            run += 1

        if run >= _OQ_MIN_RUN:
            out += [_OQ_MARKER, run, b]
            i += run
        elif b == _OQ_MARKER:
            # Escape literal marker byte
            out += [_OQ_MARKER, 0x00, _OQ_MARKER]
            i += 1
        else:
            out.append(b)
            i += 1

    return bytes(out)


def omniquant_decompress(data: bytes) -> bytes:
    """Decompress Omniquant-encoded *data*."""
    if not data:
        return b""

    out: list[int] = []
    i = 0
    n = len(data)

    while i < n:
        b = data[i]
        if b == _OQ_MARKER:
            if i + 2 >= n:
                raise ValueError(
                    f"Omniquant: truncated escape sequence at offset {i}"
                )
            count = data[i + 1]
            val = data[i + 2]
            if count == 0x00:
                # Literal marker escape
                out.append(val)
            else:
                out += [val] * count
            i += 3
        else:
            out.append(b)
            i += 1

    return bytes(out)


# ---------------------------------------------------------------------------
# Encode / decode
# ---------------------------------------------------------------------------


def _serialise_payload(msg: Host8Message) -> bytes:
    """Convert *msg.payload* to bytes according to json_zero flag."""
    if msg.json_zero:
        if isinstance(msg.payload, (bytes, bytearray)):
            return bytes(msg.payload)
        raise TypeError(
            "json=0 mode requires payload to be bytes or bytearray, "
            f"got {type(msg.payload).__name__}"
        )
    # JSON mode
    if isinstance(msg.payload, (bytes, bytearray)):
        # Wrap raw bytes as hex string for JSON transport
        return json.dumps({"_bytes": msg.payload.hex()}).encode("utf-8")
    return json.dumps(msg.payload).encode("utf-8")


def _deserialise_payload(body: bytes, json_zero: bool) -> Any:
    """Convert raw *body* bytes back to payload according to json_zero flag."""
    if json_zero:
        return body
    obj = json.loads(body.decode("utf-8"))
    # Unwrap bytes-as-hex if needed
    if isinstance(obj, dict) and list(obj.keys()) == ["_bytes"]:
        return bytes.fromhex(obj["_bytes"])
    return obj


def encode(msg: Host8Message) -> bytes:
    """Encode *msg* into Host-8 binary wire format.

    Returns:
        8-byte header + body bytes.
    """
    body = _serialise_payload(msg)

    if msg.use_omniquant:
        body = omniquant_compress(body)

    type_byte = (msg.msg_type & 0x7F) | (FLAG_JSON_ZERO if msg.json_zero else 0x00)
    header = struct.pack(">2sBBL", MAGIC, VERSION, type_byte, len(body))
    return header + body


def decode(data: bytes) -> Host8Message:
    """Decode *data* (header + body) into a :class:`Host8Message`.

    Args:
        data: Raw bytes starting at the beginning of a Host-8 frame.

    Returns:
        Populated :class:`Host8Message`.

    Raises:
        ValueError: If the magic bytes or version are wrong, or if data is
                    too short.
    """
    if len(data) < 8:
        raise ValueError(
            f"Host-8: frame too short ({len(data)} bytes); need at least 8"
        )

    magic, version, type_byte, body_len = struct.unpack(">2sBBL", data[:8])

    if magic != MAGIC:
        raise ValueError(f"Host-8: bad magic {magic!r}; expected {MAGIC!r}")
    if version != VERSION:
        raise ValueError(
            f"Host-8: unsupported version {version:#04x}; expected {VERSION:#04x}"
        )

    expected_total = 8 + body_len
    if len(data) < expected_total:
        raise ValueError(
            f"Host-8: frame declares {body_len} body bytes but only "
            f"{len(data) - 8} are available"
        )

    body = data[8:expected_total]

    json_zero = bool(type_byte & FLAG_JSON_ZERO)
    msg_type = type_byte & 0x7F

    # Omniquant: attempt decompression and detect if it was compressed.
    # We store whether decompression changed anything to inform use_omniquant.
    decompressed = omniquant_decompress(body)
    use_omniquant = decompressed != body
    if use_omniquant:
        body = decompressed

    payload = _deserialise_payload(body, json_zero)

    msg = Host8Message(
        msg_type=msg_type,
        payload=payload,
        json_zero=json_zero,
        use_omniquant=use_omniquant,
    )
    msg._raw_body = body
    return msg
