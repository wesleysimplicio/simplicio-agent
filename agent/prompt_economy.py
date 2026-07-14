"""Prompt-economy layer for issue #196.

This module implements *progressive disclosure* of the fixed per-turn token
tax — the system-prompt body (~72k chars) and the full tool-schema set — so
that a running session pays far less for capability it rarely touches, while
still keeping:

  * **deterministic tool availability** (no tool is ever hidden from the
    model — every tool is always listed in the capability bundle), and
  * **a cache-stable prefix** (the index and the bundle order are byte-stable
    for the life of a session/run, so upstream prompt-caching KV stays warm).

Two public entry points:

``resolve_instruction_index()``
    Returns a *compact instruction index*: a small, ordered list of short
    handles (e.g. ``"sec:identity"``, ``"tool:terminal"``) plus a one-line
    summary for each.  The full text of any section is resolved lazily, on
    demand, via :func:`expand_instruction` — only when the model names the
    handle.  The default payload therefore carries handles + summaries, never
    the 72k-char body.  The handle order is fixed by catalog, so it is
    deterministic and cache-stable.

``pin_capability_bundle(tools, task)``
    Returns a *task-pinned capability bundle*.  Computed once at session/run
    freeze, it reorders the **entire** tool set into a deterministic,
    task-relevant order.  The input set is never reduced: the returned bundle
    is a permutation of the input — every tool name/schema/order is preserved
    exactly, only the *sequence* is pinned.  Identical ``(tools, task)`` input
    always yields identical order, so names/schemas/order stay stable for
    prompt caching.

INVARIANTS (enforced by ``tests/agent/test_prompt_economy.py``):

  I1. ``resolve_instruction_index`` never returns full section text — only
      short handles + short summaries.
  I2. ``pin_capability_bundle`` preserves the full tool set: the returned
      bundle is a permutation of the input, never a subset or superset.
  I3. Both functions are deterministic and order-stable for identical inputs
      (no randomness, no wall-clock, no per-call mutation).
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Union

__all__ = [
    "INSTRUCTION_CATALOG",
    "resolve_instruction_index",
    "expand_instruction",
    "expand_instruction_with_receipt",
    "instruction_expansion_receipt",
    "ExpansionReceipt",
    "PromptEconomyReceipt",
    "pin_capability_bundle",
    "instruction_index_summary_size",
    "instruction_index_full_size",
    "COMPACTABLE_HANDLES",
    "render_compact_block",
    "compact_block_receipt",
]

# These are local, deterministic budgets.  They are intentionally expressed
# in characters so they do not pretend to be provider-token measurements.
# ``compact_block_receipt`` exposes the corresponding rough token counts with
# the same conservative four-characters-per-token estimate used by the rest
# of the prompt diagnostics.
INSTRUCTION_SUMMARY_MAX_CHARS = 160
COMPACT_BLOCK_MAX_CHARS = 800
_CHARS_PER_ROUGH_TOKEN = 4

# ─────────────────────────────────────────────────────────────────────────
# Compact instruction index
# ─────────────────────────────────────────────────────────────────────────

# Ordered catalog of instruction sections. The *order of this list* is the
# stable index order — it is fixed at module load and never depends on
# runtime state, which is what keeps the cached system-prompt prefix warm.
#
# Each entry:
#   handle  — short, stable identifier emitted in the compact index
#             (must be a short string; never the full text).
#   title   — human-readable section title.
#   summary — one-line (<~160 char) synopsis carried in the compact index.
#   category— coarse grouping ("identity" | "behavior" | "guidance" |
#             "platform" | "memory" | "skills").
#   symbol  — optional attribute name on ``agent.prompt_builder`` that holds
#             the full section text. When present, expand_instruction resolves
#             the real, current body; otherwise the fallback summary text is
#             used. This keeps the index honest: the long text genuinely lives
#             elsewhere and is only pulled on demand.
INSTRUCTION_CATALOG: List[Dict[str, str]] = [
    {
        "handle": "sec:identity",
        "title": "Agent identity",
        "summary": "Who the agent is (SOUL.md or default identity).",
        "category": "identity",
        "symbol": "DEFAULT_AGENT_IDENTITY",
    },
    {
        "handle": "sec:hermes-help",
        "title": "Hermes help pointer",
        "summary": "Where to look for Hermes/Simplicio docs and skills.",
        "category": "guidance",
        "symbol": "HERMES_AGENT_HELP_GUIDANCE",
    },
    {
        "handle": "sec:task-completion",
        "title": "Task completion guidance",
        "summary": "Finish the job with real artifacts; no stubs or fabricated output.",
        "category": "behavior",
        "symbol": "TASK_COMPLETION_GUIDANCE",
    },
    {
        "handle": "sec:parallel-tools",
        "title": "Parallel tool calls",
        "summary": "Batch independent tool calls into one turn.",
        "category": "behavior",
        "symbol": "PARALLEL_TOOL_CALL_GUIDANCE",
    },
    {
        "handle": "sec:memory",
        "title": "Memory guidance",
        "summary": "When/how to read and write durable memory.",
        "category": "memory",
        "symbol": "MEMORY_GUIDANCE",
    },
    {
        "handle": "sec:session-search",
        "title": "Session search",
        "summary": "Recall past sessions via session_search.",
        "category": "memory",
        "symbol": "SESSION_SEARCH_GUIDANCE",
    },
    {
        "handle": "sec:skills",
        "title": "Skills guidance",
        "summary": "Use and manage skills; skill_view/skills_list reach all.",
        "category": "skills",
        "symbol": "SKILLS_GUIDANCE",
    },
    {
        "handle": "sec:kanban",
        "title": "Kanban worker lifecycle",
        "summary": "Worker/orchestrator lifecycle when dispatched by kanban.",
        "category": "guidance",
        "symbol": "KANBAN_GUIDANCE",
    },
    {
        "handle": "sec:steer-channel",
        "title": "Out-of-band steer channel",
        "summary": "Mid-turn user steer markers are real instructions.",
        "category": "guidance",
        "symbol": "STEER_CHANNEL_NOTE",
    },
    {
        "handle": "sec:tool-use-enforcement",
        "title": "Tool-use enforcement",
        "summary": "Actually call tools instead of describing intended actions.",
        "category": "behavior",
        "symbol": "TOOL_USE_ENFORCEMENT_GUIDANCE",
    },
    {
        "handle": "sec:openai-exec",
        "title": "OpenAI/Codex/Grok execution discipline",
        "summary": "Tool persistence, prereq checks, verify before claiming done.",
        "category": "guidance",
        "symbol": "OPENAI_MODEL_EXECUTION_GUIDANCE",
    },
    {
        "handle": "sec:google-ops",
        "title": "Google operational guidance",
        "summary": "Conciseness, absolute paths, parallel calls, verify-before-edit.",
        "category": "guidance",
        "symbol": "GOOGLE_MODEL_OPERATIONAL_GUIDANCE",
    },
    {
        "handle": "sec:toon",
        "title": "Toon prompts hint",
        "summary": "When toon prompts are enabled for this session.",
        "category": "guidance",
        "symbol": "TOON_PROMPTS_HINT",
    },
    {
        "handle": "sec:computer-use",
        "title": "Computer-use guidance",
        "summary": "Driving the host desktop (macOS/Windows/Linux specifics).",
        "category": "guidance",
        "symbol": "_computer_use_guidance",
    },
    {
        "handle": "sec:platform-hint",
        "title": "Platform hint",
        "summary": "Per-platform operational hints (CLI/gateway/discord/...).",
        "category": "platform",
        "symbol": "_platform_hints",
    },
    {
        "handle": "sec:environment",
        "title": "Environment hints",
        "summary": "WSL/Termux/remote-backend environment translation notes.",
        "category": "platform",
        "symbol": "_environment_hints",
    },
    {
        "handle": "sec:profile",
        "title": "Active profile",
        "summary": "Which Hermes profile this session reads/writes.",
        "category": "platform",
        "symbol": "_active_profile_note",
    },
    {
        "handle": "sec:nous",
        "title": "Nous subscription",
        "summary": "Entitlement/subscription block when Nous tools are present.",
        "category": "guidance",
        "symbol": "_nous_subscription",
    },
]

# Index for O(1) handle lookup.
_HANDLE_INDEX: Dict[str, Dict[str, str]] = {e["handle"]: e for e in INSTRUCTION_CATALOG}


@dataclass(frozen=True)
class ExpansionReceipt:
    """Deterministic evidence for one instruction expansion.

    This is an in-memory value object rather than a telemetry event: it has no
    timestamp, provider claim, or session identifier. Repeated expansions of
    the same content are therefore directly comparable. Provider-side token
    savings must be measured by the provider and are intentionally not claimed
    here.

    ``prefix_invalidated`` is false for the normal append-only expansion path.
    A caller rebuilding a cached system prompt can set it explicitly so a
    receipt cannot accidentally imply cache preservation. ``selected_bundle``
    records an already-pinned tool order, when supplied, without changing or
    subsetting that bundle.
    """

    handle: str
    content_sha256: str
    chars: int
    bytes: int
    selected_bundle: tuple[str, ...] = ()
    fallback: bool = False
    fallback_reason: str = ""
    cache_stable: bool = True
    prefix_invalidated: bool = False

    @property
    def sha256(self) -> str:
        """Convenient alias for the canonical content hash field."""
        return self.content_sha256

    @property
    def size(self) -> int:
        """UTF-8 byte size, useful for honest wire-size accounting."""
        return self.bytes

    @property
    def content_hash(self) -> str:
        """Compatibility alias used by receipt consumers."""
        return self.content_sha256

    def to_dict(self) -> Dict[str, Any]:
        """Return a stable JSON-friendly representation."""
        return {
            "handle": self.handle,
            "content_sha256": self.content_sha256,
            "chars": self.chars,
            "bytes": self.bytes,
            "selected_bundle": list(self.selected_bundle),
            "fallback": self.fallback,
            "fallback_reason": self.fallback_reason,
            "cache_stable": self.cache_stable,
            "prefix_invalidated": self.prefix_invalidated,
        }

    as_dict = to_dict


@dataclass(frozen=True)
class PromptEconomyReceipt:
    """Deterministic local measurement for one compacted prompt slice.

    ``raw_*`` describes the full bodies that the active handles would have
    injected, while ``compact_*`` describes the bounded block actually
    rendered.  The token fields are explicitly *rough* estimates; provider
    usage and cache receipts are required for claims about billed tokens.
    There is no timestamp or mutable session state, so equal inputs produce
    equal receipts.
    """

    active_handles: tuple[str, ...]
    raw_chars: int
    compact_chars: int
    raw_tokens: int
    compact_tokens: int
    chars_saved: int
    tokens_saved: int
    raw_bytes: int
    compact_bytes: int
    compact_sha256: str
    cache_stable: bool = True

    @property
    def reduction_ratio(self) -> float:
        """Return the character reduction as a ratio in ``[0, 1]``."""
        if self.raw_chars <= 0:
            return 0.0
        return self.chars_saved / self.raw_chars

    def to_dict(self) -> Dict[str, Any]:
        """Return a stable JSON-friendly representation."""
        return {
            "active_handles": list(self.active_handles),
            "raw_chars": self.raw_chars,
            "compact_chars": self.compact_chars,
            "raw_tokens": self.raw_tokens,
            "compact_tokens": self.compact_tokens,
            "chars_saved": self.chars_saved,
            "tokens_saved": self.tokens_saved,
            "raw_bytes": self.raw_bytes,
            "compact_bytes": self.compact_bytes,
            "compact_sha256": self.compact_sha256,
            "cache_stable": self.cache_stable,
        }

    as_dict = to_dict


def resolve_instruction_index() -> List[Dict[str, str]]:
    """Return the compact instruction index.

    Each entry is ``{"handle", "title", "summary", "category"}`` — short,
    stable strings only.  The full section text is intentionally **not**
    included; resolve it on demand with :func:`expand_instruction`.

    The returned list is ordered by the fixed :data:`INSTRUCTION_CATALOG`,
    so it is byte-stable across calls and sessions (I1, I3).
    """
    return [
        {
            "handle": e["handle"],
            "title": e["title"],
            "summary": e["summary"],
            "category": e["category"],
        }
        for e in INSTRUCTION_CATALOG
    ]


def _catalog_symbol_value(symbol: str) -> Optional[str]:
    """Resolve a catalog ``symbol`` to its real text from prompt_builder.

    Returns ``None`` when the symbol is a synthetic aggregate marker (prefixed
    with ``_``) or when prompt_builder cannot be imported — callers fall back
    to the catalog ``summary``.
    """
    if symbol.startswith("_"):
        return None
    try:
        import agent.prompt_builder as pb  # local import keeps this module light
    except Exception:
        return None
    return getattr(pb, symbol, None)


def _receipt_bundle(
    selected_bundle: Optional[Sequence[Union[str, Mapping[str, Any]]]],
    tools: Optional[Sequence[Union[str, Mapping[str, Any]]]],
    task: Optional[str],
) -> tuple[str, ...]:
    """Normalize a receipt's selected bundle without changing its order."""
    if selected_bundle is None and tools is not None:
        return tuple(pin_capability_bundle_names(tools, task=task))
    if selected_bundle is None:
        return ()
    result = []
    for item in selected_bundle:
        if isinstance(item, str):
            result.append(item)
        elif isinstance(item, Mapping):
            result.append(_tool_name(item))
        else:
            result.append(str(item))
    return tuple(result)


def _build_expansion_receipt(
    handle: str,
    text: str,
    *,
    selected_bundle: Optional[Sequence[Union[str, Mapping[str, Any]]]] = None,
    tools: Optional[Sequence[Union[str, Mapping[str, Any]]]] = None,
    task: Optional[str] = None,
    fallback: bool = False,
    fallback_reason: str = "",
    cache_stable: bool = True,
    prefix_invalidated: bool = False,
) -> ExpansionReceipt:
    """Build a deterministic receipt for *text*.

    The cache flags describe the caller's insertion strategy; expanding a
    section itself never mutates the cached system prompt. If a caller marks a
    prefix as invalidated, the receipt defensively reports ``cache_stable`` as
    false even if an inconsistent true value was supplied.
    """
    prefix_invalidated = bool(prefix_invalidated)
    cache_stable = bool(cache_stable) and not prefix_invalidated
    encoded = text.encode("utf-8")
    return ExpansionReceipt(
        handle=handle,
        content_sha256=hashlib.sha256(encoded).hexdigest(),
        chars=len(text),
        bytes=len(encoded),
        selected_bundle=_receipt_bundle(selected_bundle, tools, task),
        fallback=bool(fallback),
        fallback_reason=str(fallback_reason or ""),
        cache_stable=cache_stable,
        prefix_invalidated=prefix_invalidated,
    )


def expand_instruction_with_receipt(
    handle: str,
    *,
    fallback: Optional[str] = None,
    selected_bundle: Optional[Sequence[Union[str, Mapping[str, Any]]]] = None,
    tools: Optional[Sequence[Union[str, Mapping[str, Any]]]] = None,
    task: Optional[str] = None,
    cache_stable: bool = True,
    prefix_invalidated: bool = False,
) -> tuple[str, ExpansionReceipt]:
    """Expand an instruction and return deterministic evidence beside it.

    The compact index remains cache-stable because this function only resolves
    text; callers should append the expansion as a tool-result/user-approved
    payload rather than rebuilding the stable system prompt. ``fallback`` is
    an explicit, full caller-owned fallback for unknown handles or unavailable
    source bodies. With no explicit fallback, an unknown handle retains the
    historical ``KeyError`` contract, while a known handle falls back to its
    catalog summary so a missing optional prompt-builder import never blocks a
    turn.

    ``tools`` + ``task`` is an optional convenience for recording the exact
    deterministic order returned by :func:`pin_capability_bundle`; callers
    may instead pass an already-pinned ``selected_bundle``. Neither path
    changes the tool set or claims provider-token savings.
    """
    entry = _HANDLE_INDEX.get(handle)
    if entry is None:
        if fallback is None:
            raise KeyError(f"unknown instruction handle: {handle!r}")
        text = fallback
        receipt = _build_expansion_receipt(
            handle,
            text,
            selected_bundle=selected_bundle,
            tools=tools,
            task=task,
            fallback=True,
            fallback_reason="unknown_handle",
            cache_stable=cache_stable,
            prefix_invalidated=prefix_invalidated,
        )
        return text, receipt

    full = _catalog_symbol_value(entry["symbol"])
    if isinstance(full, str) and full:
        text = full
        used_fallback = False
        reason = ""
    elif fallback is not None:
        text = fallback
        used_fallback = True
        reason = "body_unavailable"
    else:
        text = entry["summary"]
        used_fallback = True
        reason = "body_unavailable:catalog_summary"

    receipt = _build_expansion_receipt(
        handle,
        text,
        selected_bundle=selected_bundle,
        tools=tools,
        task=task,
        fallback=used_fallback,
        fallback_reason=reason,
        cache_stable=cache_stable,
        prefix_invalidated=prefix_invalidated,
    )
    return text, receipt


def instruction_expansion_receipt(
    handle: str,
    **kwargs: Any,
) -> ExpansionReceipt:
    """Return only the deterministic receipt for an instruction expansion."""
    _text, receipt = expand_instruction_with_receipt(handle, **kwargs)
    return receipt


def expand_instruction(handle: str, **kwargs: Any) -> str:
    """Lazily resolve full text while preserving the original string API.

    See :func:`expand_instruction_with_receipt` for opt-in receipts and
    explicit fallback/cache metadata. Existing callers that pass only a
    handle receive the same string (and the same unknown-handle ``KeyError``)
    as before.
    """
    text, _receipt = expand_instruction_with_receipt(handle, **kwargs)
    return text


def instruction_index_summary_size() -> int:
    """Total character length of the compact index payload."""
    total = 0
    for e in resolve_instruction_index():
        total += (
            len(e["handle"]) + len(e["title"]) + len(e["summary"]) + len(e["category"])
        )
    return total


def instruction_index_full_size() -> int:
    """Total character length if *every* section's full text were shipped."""
    total = 0
    for e in INSTRUCTION_CATALOG:
        full = _catalog_symbol_value(e["symbol"])
        total += len(full) if isinstance(full, str) else len(e["summary"])
    return total


def _rough_tokens(text: str) -> int:
    """Return a deterministic, intentionally rough token estimate."""
    return math.ceil(len(text) / _CHARS_PER_ROUGH_TOKEN) if text else 0


def _active_compactable_entries(active_handles: Sequence[str]) -> List[Dict[str, str]]:
    """Resolve active handles in catalog order, independent of input order.

    Callers often pass a set assembled from tool gates.  Iterating that set
    directly would make the stable system-prompt bytes depend on hash
    randomization.  Catalog order is the one canonical order for this layer.
    Unknown and safety-sensitive handles are ignored by design.
    """
    active = set(active_handles)
    return [
        entry
        for entry in INSTRUCTION_CATALOG
        if entry["handle"] in active and entry["handle"] in COMPACTABLE_HANDLES
    ]


# Handles safe to fold into the compact block instead of shipping full text
# every turn. Deliberately conservative (issue #196 design principle 3,
# "safety is eager"): restricted to handles whose ``symbol`` is a real,
# non-underscore ``agent.prompt_builder`` attribute (so :func:`expand_instruction`
# can genuinely recover the full body on demand — this excludes the dynamic/
# aggregate markers such as environment/platform/profile/nous, whose ``symbol``
# is prefixed with ``_`` and has no real expansion path), AND whose category is
# NOT ``identity``/``behavior`` (no-fabrication / tool-use-enforcement / parallel
# -tool guidance, and the model-family-specific OpenAI/Google execution
# discipline, always ship in full — they target concrete hallucination/
# incomplete-tool-use failure modes and are not safe to summarize away).
COMPACTABLE_HANDLES = frozenset({
    "sec:hermes-help",
    "sec:memory",
    "sec:session-search",
    "sec:skills",
    "sec:kanban",
})


def render_compact_block(
    active_handles: Sequence[str],
    *,
    max_chars: int = COMPACT_BLOCK_MAX_CHARS,
) -> str:
    """Render one compact block for the subset of *active_handles* that are
    safe to compact (see :data:`COMPACTABLE_HANDLES`).

    ``active_handles`` is the set of handles whose full-text guidance would
    otherwise have been injected this turn (i.e. gated the same way the caller
    already gates the full text — by tool availability). Handles not in
    :data:`COMPACTABLE_HANDLES` are ignored here (the caller keeps shipping
    their full text unconditionally; this function never removes anything
    from view — I4 below).

    Returns ``""`` when no compactable handle is active this turn (nothing to
    summarize), so callers can skip appending an empty block.

    INVARIANT (I4, "no invisible capability"): every rendered line names its
    handle and one-line summary — nothing is hidden, only shortened. The
    one-line summary is written to be operationally sufficient on its own
    (models already carry the matching tool schemas); genuine full-text
    recovery remains available via :func:`expand_instruction` for any caller
    (CLI diagnostics, a future interactive expansion path) that wants it.
    """
    if max_chars < 1:
        raise ValueError("max_chars must be positive")
    entries = _active_compactable_entries(active_handles)
    if not entries:
        return ""
    lines = [
        "Compact capability index (progressive disclosure, issue #196): the "
        "sections below are summarized rather than shown in full to cut the "
        "fixed per-turn prompt tax. Nothing is hidden — every active section "
        "is listed by handle; the one-line summary is normally sufficient "
        "given the matching tool schemas you already have."
    ]
    if len(lines[0]) > max_chars:
        return lines[0][:max_chars]
    for e in entries:
        summary = e["summary"][:INSTRUCTION_SUMMARY_MAX_CHARS].rstrip()
        lines.append(f"- {e['handle']} ({e['title']}): {summary}")
    block = "\n".join(lines)
    if len(block) <= max_chars:
        return block

    # On an explicitly smaller budget, retain every handle (I4) and shorten
    # only the prose.  The full default block remains byte-for-byte unchanged.
    # A short heading makes the cap useful for callers with many active tools.
    heading = "Compact capability index:\n"
    prefixes = [f"- {entry['handle']}: " for entry in entries]
    minimum = len(heading) + sum(len(prefix.rstrip()) for prefix in prefixes) + len(entries) - 1
    if minimum > max_chars:
        raise ValueError(
            f"max_chars={max_chars} is too small to name all active handles "
            f"(minimum={minimum})"
        )
    summary_budget = max_chars - minimum
    # Divide the remaining budget deterministically in catalog order, then
    # use any remainder on earlier entries.
    per_summary, remainder = divmod(summary_budget, len(entries))
    bounded_lines = []
    for index, (entry, prefix) in enumerate(zip(entries, prefixes)):
        allowance = per_summary + (1 if index < remainder else 0)
        bounded_lines.append(prefix.rstrip() + (f" {entry['summary'][:allowance]}" if allowance else ""))
    return heading.rstrip("\n") + "\n" + "\n".join(bounded_lines)


def compact_block_receipt(
    active_handles: Sequence[str],
    *,
    max_chars: int = COMPACT_BLOCK_MAX_CHARS,
) -> PromptEconomyReceipt:
    """Measure the bounded compact block without claiming provider savings."""
    entries = _active_compactable_entries(active_handles)
    handles = tuple(entry["handle"] for entry in entries)
    raw_text = " ".join(
        _catalog_symbol_value(entry["symbol"]) or entry["summary"]
        for entry in entries
    )
    compact_text = render_compact_block(handles, max_chars=max_chars)
    raw_chars = len(raw_text)
    compact_chars = len(compact_text)
    return PromptEconomyReceipt(
        active_handles=handles,
        raw_chars=raw_chars,
        compact_chars=compact_chars,
        raw_tokens=_rough_tokens(raw_text),
        compact_tokens=_rough_tokens(compact_text),
        chars_saved=max(0, raw_chars - compact_chars),
        tokens_saved=max(0, _rough_tokens(raw_text) - _rough_tokens(compact_text)),
        raw_bytes=len(raw_text.encode("utf-8")),
        compact_bytes=len(compact_text.encode("utf-8")),
        compact_sha256=hashlib.sha256(compact_text.encode("utf-8")).hexdigest(),
    )


# ─────────────────────────────────────────────────────────────────────────
# Task-pinned capability bundle
# ─────────────────────────────────────────────────────────────────────────

_Token = str


def _tokens(text: str) -> set:
    """Lowercased word tokens of *text* for stable relevance scoring."""
    return set(re.findall(r"[a-z0-9_]+", (text or "").lower()))


def _normalize_tools(
    tools: Sequence[Union[str, Mapping[str, Any]]],
) -> List[Dict[str, Any]]:
    """Coerce mixed name/definition input into a list of tool dicts.

    Accepts either:
      * a list of OpenAI-style tool definitions (``{"name": ..., ...}``), or
      * a list of bare tool-name strings.

    The returned dicts preserve the **original object reference** for any
    mapping passed in, so schemas are never mutated (I2).
    """
    normalized: List[Dict[str, Any]] = []
    for t in tools:
        if isinstance(t, str):
            normalized.append({"name": t})
        elif isinstance(t, Mapping):
            # Preserve the original mapping object (no copy) so callers get
            # back their exact schema instances in the pinned order.
            normalized.append(dict(t))  # shallow copy of the wrapper only
        else:
            raise TypeError(f"tool must be str or mapping, got {type(t).__name__}")
    return normalized


def _tool_name(tool: Mapping[str, Any]) -> str:
    """Read names from bare definitions and OpenAI function wrappers."""
    name = tool.get("name")
    if name is None and isinstance(tool.get("function"), Mapping):
        name = tool["function"].get("name")
    return str(name or "")


def _tool_description(tool: Mapping[str, Any]) -> str:
    """Read descriptions from bare definitions and OpenAI function wrappers."""
    description = tool.get("description")
    if description is None and isinstance(tool.get("function"), Mapping):
        description = tool["function"].get("description")
    return str(description or "")


def _tool_schema_fingerprint(tool: Mapping[str, Any]) -> str:
    """Canonical tie-break for duplicate-name schemas."""
    try:
        payload = json.dumps(tool, ensure_ascii=False, sort_keys=True, default=str)
    except (TypeError, ValueError):
        payload = repr(sorted((str(k), repr(v)) for k, v in tool.items()))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def pin_capability_bundle(
    tools: Sequence[Union[str, Mapping[str, Any]]],
    task: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Pin a task-relevant, cache-stable ordering of the *full* tool set.

    Progressive disclosure at the schema layer: instead of rebuilding or
    subsetting the tool list every turn (which would invalidate the cached
    prefix), this is computed **once at session/run freeze** and reused.  It
    reorders the complete tool set so task-relevant tools float to the front,
    but it never drops a tool — availability is fully preserved (I2).

    Determinism / cache stability (I3):
      * Task relevance is scored from word-token overlap between the task and
        each tool's name + description (stable, no randomness).
      * Ties are broken by lexicographic tool name, so identical
        ``(tools, task)`` input always yields identical order.
      * The task is reduced to an order-insensitive digest, so the pinned
        order does not depend on incidental arg formatting.

    Args:
        tools: complete tool set — names (``str``) or definitions
            (``{"name": ..., "description": ..., ...}``). Every entry is
            returned; none are removed.
        task: optional task description used to rank tools. ``None`` yields a
            pure lexicographic (still deterministic) order.

    Returns:
        A new list containing the **same** tool entries (same names/schemas),
        reordered.  It is a permutation of the input.
    """
    normalized = _normalize_tools(tools)
    if not normalized:
        return []

    task_tokens = _tokens(task or "")
    # Pre-compute a stable relevance key per tool.
    scored = []
    for tool in normalized:
        name = _tool_name(tool)
        desc = _tool_description(tool)
        blob = f"{name} {desc}"
        tool_tokens = _tokens(blob)
        # Overlap count: how many task tokens appear in this tool's name/desc.
        overlap = len(task_tokens & tool_tokens) if task_tokens else 0
        # Name-prefix hits weigh slightly more (a tool literally named for the
        # task is almost certainly relevant). Deterministic, no randomness.
        name_token_hits = len(task_tokens & _tokens(name)) if task_tokens else 0
        score = overlap + 2 * name_token_hits
        # Sort key: higher score first, then lexicographic name for a stable
        # tiebreak.  The schema fingerprint only matters for malformed/duplicate tool
        # names; normal tool registries have unique names.  It makes the
        # ordering independent of the input list order without mutating any
        # schema or dropping duplicates.
        scored.append(((-score, name, _tool_schema_fingerprint(tool)), tool))

    scored.sort(key=lambda kv: kv[0])
    return [tool for _, tool in scored]


def pin_capability_bundle_names(
    tools: Sequence[Union[str, Mapping[str, Any]]],
    task: Optional[str] = None,
) -> List[str]:
    """Convenience wrapper: return only the pinned tool-name ordering."""
    return [_tool_name(t) for t in pin_capability_bundle(tools, task=task)]
