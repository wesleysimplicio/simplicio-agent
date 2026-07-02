"""TOON (Token-Oriented Object Notation) encoder/decoder.

TOON is a compact, lossless, whitespace-indented text encoding for JSON-like
data (dicts / lists / scalars) designed to spend fewer LLM tokens than
``json.dumps`` for the same payload — most of the win comes from arrays of
uniform objects, which collapse a repeated set of ``{"key": ...}`` wrappers
into one header line + one CSV-ish row per element.

Reference: https://github.com/toon-format/toon

This module is conformance-tested against the shared ecosystem spec —
``TOON-CONTRACT.md`` (vendored at the repo root from
https://github.com/wesleysimplicio/simplicio-mapper, issue #149) — via the
golden corpus at ``tests/fixtures/toon-golden/`` and
``scripts/toon_contract_runner.py`` (issue #16). Encoding/decoding rules
below follow that contract; see it for the full spec and rationale.

Grammar (informal):

    object:  one ``key: value`` line per entry, nested objects indented
             two spaces per level (YAML-style)::

                 key:
                   nested: 1

    uniform array-of-objects (all elements are dicts with the exact same
    key set and every value is a scalar, or a list of scalars) → tabular
    block, one row per element, a list-of-scalars cell rendered inline as
    a bracketed group::

                 items[2]{id,name,tags}:
                   1,Alice,[a,b]
                   2,Bob,[]

    array of scalars → inline list::

                 tags[3]: a,b,c

    anything else (empty array, non-uniform objects, mixed types, a
    dict-valued cell, or a cell holding a list of non-scalars) → falls back
    to compact JSON for that value, e.g. ``key: [1,{"a":1}]``. This keeps
    the format always lossless even when it can't compress. Every such
    fallback is recorded per TOON-CONTRACT.md §3 (see ``to_toon_report``).

Public surface:

    to_toon(value) -> str          Encode any JSON-compatible value to TOON text.
    to_toon_report(value) -> (str, list[dict])
                                    Like ``to_toon``, plus the §3 fallback report.
    from_toon(text) -> Any         Decode TOON text back to the original value.

``decode(encode(x)) == x`` holds for any JSON-compatible ``x`` (dict, list,
str, int, float, bool, None, and arbitrary nesting thereof).
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, List, Tuple

logger = logging.getLogger(__name__)

__all__ = [
    "to_toon",
    "to_toon_report",
    "from_toon",
    "to_toon_or_json",
    "parse_tool_payload",
    "ToonDecodeError",
]


class ToonDecodeError(ValueError):
    """Raised when ``from_toon`` receives text it cannot parse.

    Always a ``ValueError`` subclass, never a bare index/key/attribute
    error that leaks the parser's internal state (TOON-CONTRACT.md §5).
    """


# ---------------------------------------------------------------------------
# Shared regexes
# ---------------------------------------------------------------------------

# A "key" is any run of characters that doesn't start with something that
# would make it ambiguous with a JSON fallback blob (``{``/``[``/``"``) and
# doesn't contain the punctuation TOON itself uses as delimiters.
_KEY = r'[^\s:\[\]{}"][^:\[\]{}"]*'

# ``key:`` / ``key: value``  (also matches with an empty key for the
# rootless-array case, since the key group is optional).
_KEY_LINE_RE = re.compile(rf'^(?P<indent>[ ]*)(?P<key>{_KEY}):[ ]?(?P<value>.*)$')

# ``key[N]{f1,f2,...}:``  — tabular array header. Key is optional (root array).
_TABLE_HEADER_RE = re.compile(
    rf'^(?P<indent>[ ]*)(?P<key>{_KEY})?\[(?P<n>\d+)\]\{{(?P<fields>[^}}]*)\}}:[ ]*$'
)

# ``key[N]: v1,v2,...``  — inline scalar array header. Key is optional.
_SCALAR_ARRAY_HEADER_RE = re.compile(
    rf'^(?P<indent>[ ]*)(?P<key>{_KEY})?\[(?P<n>\d+)\]:[ ]?(?P<value>.*)$'
)

_RESERVED_WORDS = ("null", "true", "false")


# ---------------------------------------------------------------------------
# Encoding
# ---------------------------------------------------------------------------


def to_toon(value: Any) -> str:
    """Encode ``value`` (dict/list/scalar, JSON-compatible) as TOON text."""

    lines: List[str] = []
    _encode_root(value, lines, "$", None)
    return "\n".join(lines)


def to_toon_report(value: Any) -> Tuple[str, List[dict]]:
    """Like :func:`to_toon`, but also returns the TOON-CONTRACT.md §3
    fallback report: every array that could not take the tabular or
    inline-scalar shape, as ``{"path": ..., "reason": ...}``.

    ``path`` is a ``$``-rooted dotted path to the key holding the array
    (list elements are not enumerated individually — the array itself is
    one report entry). ``reason`` is one of ``differing_keys``,
    ``mixed_types``, ``nested_containers``.

    ``to_toon`` itself keeps its plain ``str``-returning signature (100+
    call sites per issue #16 rely on that); reach for this variant only
    when a caller actually wants the structured report instead of just the
    debug log line every fallback already emits.
    """

    lines: List[str] = []
    report: List[dict] = []
    _encode_root(value, lines, "$", report)
    return "\n".join(lines), report


def _encode_root(value: Any, lines: List[str], path: str, report: List[dict] | None) -> None:
    if isinstance(value, dict):
        if not value:
            lines.append("{}")
            return
        for key, sub_value in value.items():
            _encode_entry(str(key), sub_value, 0, lines, f"{path}.{key}", report)
    elif isinstance(value, list):
        _encode_array(None, value, 0, lines, path, report)
    else:
        lines.append(_format_scalar(value))


def _encode_entry(
    key: str, value: Any, indent: int, lines: List[str], path: str, report: List[dict] | None
) -> None:
    pad = " " * indent
    if isinstance(value, dict):
        if not value:
            lines.append(f"{pad}{key}: {{}}")
            return
        lines.append(f"{pad}{key}:")
        for sub_key, sub_value in value.items():
            _encode_entry(str(sub_key), sub_value, indent + 2, lines, f"{path}.{sub_key}", report)
    elif isinstance(value, list):
        _encode_array(key, value, indent, lines, path, report)
    else:
        lines.append(f"{pad}{key}: {_format_scalar(value)}")


def _encode_array(
    key: str | None, arr: list, indent: int, lines: List[str], path: str, report: List[dict] | None
) -> None:
    pad = " " * indent
    prefix = f"{pad}{key}" if key is not None else pad.rstrip()
    kind, fields = _array_kind(arr)

    if kind == "table":
        header = f"{prefix}[{len(arr)}]{{{','.join(fields)}}}:"
        lines.append(header)
        row_pad = " " * (indent + 2)
        for row in arr:
            lines.append(row_pad + _format_row(row, fields))
    elif kind == "scalar":
        body = ",".join(_format_scalar(x) for x in arr)
        lines.append(f"{prefix}[{len(arr)}]: {body}")
    elif kind == "empty":
        # Canonical, lossless encoding for an empty array (TOON-CONTRACT.md
        # §4) — not a lossy fallback, so it is NOT recorded in the report.
        if key is not None:
            lines.append(f"{pad}{key}: []")
        else:
            lines.append("[]")
    else:
        _log_fallback(path, kind, report)
        blob = _compact_json(arr)
        if key is not None:
            lines.append(f"{pad}{key}: {blob}")
        else:
            lines.append(blob)


def _array_kind(arr: list) -> Tuple[str, List[str]]:
    """Classify an array for encoding purposes.

    Returns ``(kind, fields)`` where ``kind`` is one of ``"table"``,
    ``"scalar"``, ``"empty"``, or a TOON-CONTRACT.md §3 fallback reason
    (``"differing_keys"``, ``"mixed_types"``, ``"nested_containers"``).
    ``fields`` is only meaningful for ``"table"``.
    """

    if not arr:
        return "empty", []

    if all(isinstance(x, dict) for x in arr):
        fields = list(arr[0].keys())
        for item in arr:
            if list(item.keys()) != fields:
                return "differing_keys", []
        for item in arr:
            for v in item.values():
                if not _is_tabular_cell_value(v):
                    return "nested_containers", []
        return "table", [str(f) for f in fields]

    if all(_is_scalar(x) for x in arr):
        return "scalar", []

    return "mixed_types", []


def _is_tabular_cell_value(v: Any) -> bool:
    """A value a uniform-object array's tabular path can hold in one cell:
    a scalar, or a list of scalars (TOON-CONTRACT.md §4 "list cell" rule,
    fixed upstream in simplicio-mapper#148). A dict, or a list containing a
    dict/list, forces the whole array to fall back to an embedded JSON blob
    instead (reason ``nested_containers``).
    """
    if _is_scalar(v):
        return True
    if isinstance(v, list):
        return all(_is_scalar(x) for x in v)
    return False


def _format_row(row: dict, fields: List[str]) -> str:
    return ",".join(_format_cell(row[f]) for f in fields)


def _format_cell(v: Any) -> str:
    """Format one tabular cell: a scalar, or a list of scalars rendered as
    a bracketed, comma-separated inline group (``[a,b,c]``; ``[]`` when
    empty) — TOON-CONTRACT.md §4.
    """
    if isinstance(v, list):
        return "[" + ",".join(_format_scalar(x) for x in v) + "]"
    return _format_scalar(v)


def _is_scalar(v: Any) -> bool:
    return v is None or isinstance(v, (bool, int, float, str))


def _looks_like_number(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False


def _needs_quote(s: str) -> bool:
    if s == "":
        return True
    if s != s.strip():
        return True
    if any(c in s for c in (",", ":", "\n", "\r")):
        return True
    if s[0] in ('"', "{", "["):
        return True
    if s in _RESERVED_WORDS:
        return True
    if _looks_like_number(s):
        return True
    return False


def _format_scalar(v: Any) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return repr(v)
    if isinstance(v, str):
        if _needs_quote(v):
            return json.dumps(v, ensure_ascii=False)
        return v
    raise TypeError(f"to_toon cannot encode scalar of type {type(v).__name__!r}")


def _compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _log_fallback(path: str, reason: str, report: List[dict] | None) -> None:
    """Record a TOON-CONTRACT.md §3 fallback: an array that could not take
    the tabular or inline-scalar shape and was embedded as compact JSON
    instead.

    Always logged in the contract's own shape — closes the open DoD item
    from #144/#88/#75/#93/#301 ("log do motivo"), silent in every
    implementation before this. Additionally collected into ``report`` when
    the caller wants the structured list (see ``to_toon_report``).
    """
    entry = {"path": path, "reason": reason}
    logger.debug(
        "to_toon fallback: %s",
        json.dumps({"toon_fallbacks": [entry]}, ensure_ascii=False),
    )
    if report is not None:
        report.append(entry)


# ---------------------------------------------------------------------------
# Decoding
# ---------------------------------------------------------------------------


def from_toon(text: str) -> Any:
    """Decode TOON ``text`` back into the original Python value."""

    normalized = text.replace("\r\n", "\n").rstrip("\n")
    if normalized == "":
        return {}

    lines = normalized.split("\n")
    first = lines[0]

    m_table = _TABLE_HEADER_RE.match(first)
    if m_table and not m_table.group("key"):
        # Rootless array header: the whole document is a tabular array.
        n = int(m_table.group("n"))
        fields = _split_fields(m_table.group("fields"))
        rows, _next = _read_table_rows(lines, 1, indent=2, n=n, fields=fields)
        return [dict(zip(fields, row)) for row in rows]

    m_scalar = _SCALAR_ARRAY_HEADER_RE.match(first)
    if m_scalar and not m_scalar.group("key"):
        # Rootless array header: the whole document is a scalar array.
        n = int(m_scalar.group("n"))
        return _decode_scalar_array_body(m_scalar.group("value"), n)

    m_kv = _KEY_LINE_RE.match(first)
    has_root_key = (
        (m_table is not None and m_table.group("key"))
        or (m_scalar is not None and m_scalar.group("key"))
        or (m_kv is not None and m_kv.group("key"))
    )
    if has_root_key:
        obj, _next = _decode_object(lines, 0, 0)
        return obj

    # Root scalar or a raw JSON fallback blob (``{}``, ``[]``, ``"str"``, ...).
    try:
        return json.loads(normalized)
    except (ValueError, TypeError):
        pass

    # An unquoted line starting with ``[`` that is neither a valid TOON
    # array header nor valid JSON can only be a broken attempt at one — a
    # genuine scalar string starting with ``[`` is always quoted at encode
    # time (``_needs_quote``), so this is unambiguous by construction
    # (TOON-CONTRACT.md §5, the same reasoning behind the ``[1]``-cell
    # disambiguation rule).
    if first.strip().startswith("["):
        raise ToonDecodeError(f"Malformed array header: {first!r}")

    return _parse_scalar(normalized)


def _indent_of(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _decode_object(lines: List[str], idx: int, indent: int) -> Tuple[dict, int]:
    result: dict = {}
    n = len(lines)
    while idx < n:
        line = lines[idx]
        if line.strip() == "":
            idx += 1
            continue
        cur_indent = _indent_of(line)
        if cur_indent != indent:
            break

        m_table = _TABLE_HEADER_RE.match(line)
        if m_table and m_table.group("key"):
            key = m_table.group("key")
            count = int(m_table.group("n"))
            fields = _split_fields(m_table.group("fields"))
            rows, idx = _read_table_rows(lines, idx + 1, indent + 2, count, fields)
            result[key] = [dict(zip(fields, row)) for row in rows]
            continue

        m_scalar_arr = _SCALAR_ARRAY_HEADER_RE.match(line)
        if m_scalar_arr and m_scalar_arr.group("key"):
            key = m_scalar_arr.group("key")
            count = int(m_scalar_arr.group("n"))
            result[key] = _decode_scalar_array_body(m_scalar_arr.group("value"), count)
            idx += 1
            continue

        m_kv = _KEY_LINE_RE.match(line)
        if m_kv:
            key = m_kv.group("key")
            value_str = m_kv.group("value")
            if value_str == "" and _has_nested_block(lines, idx, indent):
                sub, idx = _decode_object(lines, idx + 1, indent + 2)
                result[key] = sub
            else:
                result[key] = _decode_scalar_or_json(value_str)
                idx += 1
            continue

        raise ToonDecodeError(f"cannot parse TOON line: {line!r}")

    return result, idx


def _has_nested_block(lines: List[str], idx: int, indent: int) -> bool:
    nxt = idx + 1
    if nxt >= len(lines):
        return False
    nxt_line = lines[nxt]
    if nxt_line.strip() == "":
        return False
    return _indent_of(nxt_line) > indent


def _decode_scalar_or_json(value_str: str) -> Any:
    s = value_str.strip()
    if s[:1] in ("{", "["):
        return json.loads(s)
    return _parse_scalar(s)


def _read_table_rows(
    lines: List[str], idx: int, indent: int, n: int, fields: List[str]
) -> Tuple[List[List[Any]], int]:
    rows: List[List[Any]] = []
    count = 0
    total = len(lines)
    while count < n and idx < total:
        line = lines[idx]
        if line.strip() != "" and _indent_of(line) != indent:
            # Dedented (or over-indented) line: not a data row for this
            # table — the declared row count was not actually satisfied.
            break
        # A row for a zero-field table is just the indent padding (blank
        # after stripping) — still a real row, not a separator to skip.
        stripped = line.strip()
        tokens = _split_row(stripped) if stripped else []
        if len(tokens) != len(fields):
            raise ToonDecodeError(
                f"Row/field count mismatch: expected {len(fields)} field(s), "
                f"got {len(tokens)}: {stripped!r}"
            )
        rows.append([_parse_cell(t) for t in tokens])
        idx += 1
        count += 1
    if count < n:
        raise ToonDecodeError(f"Truncated tabular block: declared {n} row(s), found {count}")
    return rows, idx


def _decode_scalar_array_body(raw: str, n: int) -> list:
    raw = raw.strip()
    if n == 0 or raw == "":
        if n != 0:
            raise ToonDecodeError(f"Truncated scalar array: declared {n} element(s), found 0")
        return []
    tokens = _split_row(raw)
    if len(tokens) != n:
        raise ToonDecodeError(
            f"Truncated scalar array: declared {n} element(s), found {len(tokens)}"
        )
    return [_parse_scalar(t) for t in tokens]


def _split_fields(raw: str) -> List[str]:
    raw = raw.strip()
    if raw == "":
        return []
    return [f.strip() for f in raw.split(",")]


def _split_row(line: str) -> List[str]:
    """Split a comma-separated row into fields, respecting quoted strings
    and bracketed list cells.

    Quoted fields (``"..."``) may contain literal commas; a backslash
    inside a quoted field escapes the following character (mirrors the
    escaping ``json.dumps`` produces when a scalar needed quoting). A
    bracketed field (``[...]``, the list-cell rule, TOON-CONTRACT.md §4)
    keeps its inner commas together as one field; quoted elements nested
    inside the brackets are respected too.
    """

    fields: List[str] = []
    i = 0
    n = len(line)
    while True:
        if i < n and line[i] == '"':
            start = i
            i = _skip_quoted(line, i)
            fields.append(line[start:i])
        elif i < n and line[i] == "[":
            start = i
            i = _skip_bracketed(line, i)
            fields.append(line[start:i])
        else:
            start = i
            while i < n and line[i] != ",":
                i += 1
            fields.append(line[start:i])
        if i < n and line[i] == ",":
            i += 1
            continue
        break
    return fields


def _skip_quoted(line: str, i: int) -> int:
    """Return the index just past the closing quote of a ``"..."`` token
    starting at ``line[i] == '"'`` — or past the end of ``line`` if the
    quote is never closed. This tokenizer does not itself raise on an
    unterminated quote; ``_parse_scalar`` (via ``json.loads``) is what
    turns that into a ``ToonDecodeError``.
    """
    n = len(line)
    i += 1
    while i < n:
        if line[i] == "\\" and i + 1 < n:
            i += 2
            continue
        if line[i] == '"':
            i += 1
            break
        i += 1
    return i


def _skip_bracketed(line: str, i: int) -> int:
    """Return the index just past the closing ``]`` of a ``[...]`` list-cell
    token starting at ``line[i] == '['``, respecting nested quotes (a comma
    or bracket character inside a quoted element does not affect bracket
    depth) and, defensively, nested brackets.
    """
    n = len(line)
    depth = 0
    while i < n:
        ch = line[i]
        if ch == '"':
            i = _skip_quoted(line, i)
            continue
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            i += 1
            if depth == 0:
                break
            continue
        i += 1
    return i


def _parse_cell(token: str) -> Any:
    """Parse one tabular cell: a scalar, or a bracketed list-of-scalars
    (TOON-CONTRACT.md §4/§5).

    A bare ``[1]``-shaped token always decodes as a one-element list, never
    the scalar ``1`` — unambiguous by construction, since a genuine scalar
    string starting with ``[`` is always quoted at encode time
    (``_needs_quote``).
    """
    stripped = token.strip()
    if stripped.startswith("[") and stripped.endswith("]") and len(stripped) >= 2:
        inner = stripped[1:-1].strip()
        if inner == "":
            return []
        return [_parse_scalar(t) for t in _split_row(inner)]
    return _parse_scalar(stripped)


def _parse_scalar(token: str) -> Any:
    token = token.strip()
    if token == "null":
        return None
    if token == "true":
        return True
    if token == "false":
        return False
    if token[:1] == '"':
        # Anything starting with a literal quote is a quoted TOON scalar --
        # decode it as JSON so an unterminated or otherwise-invalid quoted
        # string raises a typed error (TOON-CONTRACT.md §5) instead of
        # silently passing the raw, still-quoted text through.
        try:
            return json.loads(token)
        except (ValueError, TypeError) as error:
            raise ToonDecodeError(f"Unterminated or invalid quoted scalar: {token!r}") from error
    if re.fullmatch(r"[+-]?\d+", token):
        return int(token)
    try:
        return float(token)
    except ValueError:
        return token


# ---------------------------------------------------------------------------
# Convenience wrappers shared by every call site that embeds structured data
# in an LLM prompt/tool-result (issue #14/#16) — a single place to fall back
# safely and to reverse the process for code that re-parses a *historical*
# tool message.
# ---------------------------------------------------------------------------


def to_toon_or_json(value: Any) -> str:
    """Encode ``value`` as TOON; fall back to compact JSON if that raises.

    Drop-in replacement for ``json.dumps(value, ...)`` at any prompt/tool
    payload site. ``to_toon`` already falls back to compact JSON *per value*
    for shapes it can't compress (non-uniform arrays, etc.) — this wrapper
    is the outer safety net for anything ``to_toon`` itself can't handle
    (e.g. an unexpected scalar type), so a payload site never raises just
    because it switched encoders.
    """
    try:
        return to_toon(value)
    except Exception:
        logger.debug("to_toon_or_json: to_toon raised, falling back to json.dumps", exc_info=True)
        return _compact_json(value)


def parse_tool_payload(text: Any) -> Any:
    """Best-effort structured parse of a tool-result string: JSON then TOON.

    Code that re-parses a *historical* tool message's content (e.g.
    ``agent.tool_result_classification``, the trajectory converter in
    ``agent.agent_runtime_helpers``, ``agent.background_review``) cannot
    assume the string is JSON any more — when ``context.toon_prompts`` was
    on for that session, ``agent.toon_boundary`` re-encoded it as TOON
    before it was appended to the message history. This tries JSON first
    (cheap, and still the common case), then TOON, and returns ``None`` if
    neither parse succeeds — the same "give up" signal a bare
    ``json.loads`` raising would have produced for callers that already
    guard with ``isinstance(data, dict)``.
    """
    if not isinstance(text, str):
        return None
    stripped = text.strip()
    if not stripped:
        return None
    try:
        return json.loads(stripped)
    except (ValueError, TypeError):
        pass
    try:
        return from_toon(stripped)
    except Exception:
        return None
