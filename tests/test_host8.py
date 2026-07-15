"""Tests for agent/hyper_bechs/host8.py — stdlib only, no external deps."""

import sys
import os

# Ensure the project root is on sys.path so we can import agent.*
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from agent.hyper_bechs.host8 import (
    MAGIC,
    VERSION,
    MSG_TYPE_DATA,
    MSG_TYPE_CONTROL,
    MSG_TYPE_ACK,
    MSG_TYPE_ERROR,
    FLAG_JSON_ZERO,
    Host8Message,
    encode,
    decode,
    omniquant_compress,
    omniquant_decompress,
)


# ---------------------------------------------------------------------------
# 1. Header structure
# ---------------------------------------------------------------------------


class TestHeader:
    """Validate the 8-byte header format."""

    def test_magic_and_version_in_header(self):
        msg = Host8Message(msg_type=MSG_TYPE_DATA, payload={"hello": "world"})
        frame = encode(msg)
        assert frame[:2] == MAGIC, "First 2 bytes must be magic b'H8'"
        assert frame[2] == VERSION, "Third byte must be version 0x01"

    def test_header_length_field(self):
        import struct

        payload = {"key": "value"}
        msg = Host8Message(msg_type=MSG_TYPE_DATA, payload=payload)
        frame = encode(msg)
        _, _, _, body_len = struct.unpack(">2sBBL", frame[:8])
        assert body_len == len(frame) - 8, "length field must equal body size"

    def test_json_zero_flag_in_type_byte(self):
        msg = Host8Message(msg_type=MSG_TYPE_DATA, payload=b"\x01\x02\x03", json_zero=True)
        frame = encode(msg)
        type_byte = frame[3]
        assert type_byte & FLAG_JSON_ZERO, "FLAG_JSON_ZERO must be set when json_zero=True"
        assert not (type_byte & FLAG_JSON_ZERO) ^ FLAG_JSON_ZERO  # same check

    def test_no_json_zero_flag_when_json_mode(self):
        msg = Host8Message(msg_type=MSG_TYPE_DATA, payload={"a": 1}, json_zero=False)
        frame = encode(msg)
        type_byte = frame[3]
        assert not (type_byte & FLAG_JSON_ZERO), "FLAG_JSON_ZERO must NOT be set in JSON mode"


# ---------------------------------------------------------------------------
# 2. Encode / decode round-trip
# ---------------------------------------------------------------------------


class TestEncodeDecode:
    """Encode → decode must reproduce original payload."""

    def test_roundtrip_json_dict(self):
        original = {"agent": "simplicio", "version": 37}
        msg = Host8Message(msg_type=MSG_TYPE_DATA, payload=original)
        recovered = decode(encode(msg))
        assert recovered.payload == original
        assert recovered.msg_type == MSG_TYPE_DATA
        assert recovered.json_zero is False

    def test_roundtrip_json_list(self):
        original = [1, 2, 3, "four", None, True]
        msg = Host8Message(msg_type=MSG_TYPE_CONTROL, payload=original)
        recovered = decode(encode(msg))
        assert recovered.payload == original
        assert recovered.msg_type == MSG_TYPE_CONTROL

    def test_roundtrip_json_zero_bytes(self):
        """json=0 mode: raw bytes pass through unchanged."""
        original = bytes(range(16))
        msg = Host8Message(msg_type=MSG_TYPE_ACK, payload=original, json_zero=True)
        recovered = decode(encode(msg))
        assert recovered.payload == original
        assert recovered.json_zero is True

    def test_roundtrip_json_zero_empty(self):
        msg = Host8Message(msg_type=MSG_TYPE_DATA, payload=b"", json_zero=True)
        recovered = decode(encode(msg))
        assert recovered.payload == b""
        assert recovered.json_zero is True

    def test_roundtrip_all_msg_types(self):
        for t in (MSG_TYPE_DATA, MSG_TYPE_CONTROL, MSG_TYPE_ACK, MSG_TYPE_ERROR):
            msg = Host8Message(msg_type=t, payload={"t": t})
            recovered = decode(encode(msg))
            assert recovered.msg_type == t

    def test_roundtrip_string_payload(self):
        msg = Host8Message(payload="hello host-8")
        recovered = decode(encode(msg))
        assert recovered.payload == "hello host-8"

    def test_roundtrip_integer_payload(self):
        msg = Host8Message(payload=42)
        recovered = decode(encode(msg))
        assert recovered.payload == 42


# ---------------------------------------------------------------------------
# 3. Omniquant compression
# ---------------------------------------------------------------------------


class TestOmniquant:
    """Omniquant encode → decode must be lossless and compress runs."""

    def test_compress_decompress_trivial(self):
        data = b"ABCDEFGH"
        assert omniquant_decompress(omniquant_compress(data)) == data

    def test_compress_decompresses_run(self):
        data = b"\xAA" * 20
        compressed = omniquant_compress(data)
        # Should be 3 bytes (marker + count + byte) instead of 20
        assert len(compressed) < len(data)
        assert omniquant_decompress(compressed) == data

    def test_no_compression_short_run(self):
        """Runs shorter than 4 are NOT compressed."""
        data = b"\xBB\xBB\xBB"  # run of 3
        compressed = omniquant_compress(data)
        assert compressed == data  # no run encoding

    def test_compress_escape_marker_byte(self):
        """Literal 0xFE bytes in data are properly escaped."""
        data = bytes([0xFE])
        compressed = omniquant_compress(data)
        assert omniquant_decompress(compressed) == data

    def test_compress_mixed_data(self):
        data = b"Hello" + b"\x00" * 10 + b"World" + b"\xFF" * 5 + b"!"
        assert omniquant_decompress(omniquant_compress(data)) == data

    def test_empty(self):
        assert omniquant_compress(b"") == b""
        assert omniquant_decompress(b"") == b""

    def test_long_run_split(self):
        """Runs > 255 are split into multiple triplets."""
        data = b"\xCC" * 500
        compressed = omniquant_compress(data)
        assert omniquant_decompress(compressed) == data

    def test_roundtrip_with_omniquant_flag(self):
        """encode/decode with use_omniquant=True produce correct payload."""
        repeated_payload = b"\xAB" * 50
        msg = Host8Message(
            msg_type=MSG_TYPE_DATA,
            payload=repeated_payload,
            json_zero=True,
            use_omniquant=True,
        )
        frame = encode(msg)
        recovered = decode(frame)
        assert recovered.payload == repeated_payload


# ---------------------------------------------------------------------------
# 4. Error cases
# ---------------------------------------------------------------------------


class TestErrorCases:
    def test_bad_magic_raises(self):
        import struct

        good_frame = encode(Host8Message(payload={}))
        bad_frame = b"XX" + good_frame[2:]  # wrong magic
        with pytest.raises(ValueError, match="bad magic"):
            decode(bad_frame)

    def test_too_short_raises(self):
        with pytest.raises(ValueError, match="too short"):
            decode(b"\x00" * 4)

    def test_truncated_body_raises(self):
        frame = encode(Host8Message(payload={"big": "data"}))
        with pytest.raises(ValueError, match="body bytes"):
            decode(frame[:-2])  # truncate the body

    def test_json_zero_requires_bytes(self):
        msg = Host8Message(payload={"not": "bytes"}, json_zero=True)
        with pytest.raises(TypeError, match="json=0"):
            encode(msg)
