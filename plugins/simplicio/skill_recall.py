"""Adaptive neural skill selection for the bundled Simplicio plugin.

The catalog is cached after the first turn; only skill handles are injected.
Full skill bodies remain behind ``skill_view`` so prompt caching stays stable.
"""

from __future__ import annotations

import math
import os
import re
import sqlite3
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Any

DB_PATH = Path.home() / ".simplicio" / "memory" / "simplicio-memory.sqlite"
TOP_K = max(1, min(5, int(os.getenv("SIMPLICIO_SKILL_RECALL_TOP_K", "3"))))
MIN_SCORE = float(os.getenv("SIMPLICIO_SKILL_RECALL_MIN_SCORE", "1.2"))

# A bounded direct path for a single browser artifact. It deliberately avoids
# planner/orchestrator overhead: the implementation is already fully scoped.
_STANDALONE_WEB_RE = re.compile(
    r"\b(?:html|css)\b.*\b(?:javascript|js)\b|\b(?:javascript|js)\b.*\b(?:html|css)\b",
    re.IGNORECASE | re.DOTALL,
)
_STANDALONE_ACTION_RE = re.compile(
    r"\b(?:build|create|write|make|crie|criar|escreva|faca|faça)\b",
    re.IGNORECASE,
)

_STOP = {
    "a", "as", "ao", "aos", "com", "como", "da", "das", "de", "do", "dos",
    "e", "em", "essa", "esse", "esta", "este", "eu", "isso", "na", "nas",
    "no", "nos", "o", "os", "ou", "para", "por", "que", "se", "um", "uma",
    "the", "a", "an", "and", "for", "from", "how", "in", "is", "of", "on",
    "or", "that", "this", "to", "with", "you", "we",
}
_TRIVIAL = {
    "bom", "boa", "dia", "noite", "ola", "oi", "obrigado", "obrigada", "valeu",
    "hello", "hey", "hi", "thanks", "thank",
}
_SYNONYMS = {
    "arquitetura": {"architecture", "architectural", "design", "codebase"},
    "bug": {"bug", "bugs", "debug", "diagnose", "diagnosing"},
    "corrigir": {"fix", "debug", "repair"},
    "diagnosticar": {"diagnose", "diagnosing", "debug", "bug"},
    "diagnostico": {"diagnose", "diagnosing", "debug", "bug"},
    "ensinar": {"teach", "learning"},
    "escrever": {"writing", "write"},
    "implementar": {"implement", "implementation", "build"},
    "modulo": {"module", "modules", "interface", "seam"},
    "modulos": {"module", "modules", "interface", "seam"},
    "profundo": {"deep", "module", "design"},
    "profundos": {"deep", "module", "design"},
    "pesquisar": {"research", "investigate", "sources"},
    "planejar": {"plan", "planning", "spec", "tickets"},
    "regressao": {"regression", "bug", "diagnosing"},
    "revisar": {"review", "code", "standards", "spec"},
    "tarefa": {"task", "tasks", "implement"},
    "tarefas": {"task", "tasks", "implement"},
    "teste": {"test", "testing", "tdd", "red", "green", "refactor"},
    "testes": {"test", "testing", "tdd", "red", "green", "refactor"},
}


def _disabled() -> bool:
    values = (
        os.getenv("SIMPLICIO_PLUGIN_DISABLE", ""),
        os.getenv("SIMPLICIO_SKILL_RECALL_DISABLE", ""),
    )
    return any(value.strip().lower() in {"1", "true", "yes", "on"} for value in values)


def _norm(text: str) -> str:
    return "".join(
        ch for ch in unicodedata.normalize("NFKD", text.lower())
        if not unicodedata.combining(ch)
    )


def _tokens(text: str) -> set[str]:
    normalized = _norm(text).replace("-", " " ).replace("_", " " ).replace("/", " " )
    return {
        token for token in re.findall(r"[a-z0-9][a-z0-9]{1,}", normalized)
        if token not in _STOP
    }


def _expanded_query(text: str) -> set[str]:
    base = _tokens(text)
    expanded = set(base)
    for token in base:
        expanded.update(_SYNONYMS.get(token, ()))
    return expanded


def _canonical_skill_handle(name: str, artifact_path: str) -> str:
    """Return a stable loadable handle instead of an ambiguous bare name."""
    normalized = artifact_path.replace("\\", "/").rstrip("/")
    marker = "/skills/"
    if marker not in normalized:
        return name
    relative = normalized.rsplit(marker, 1)[1]
    if relative.endswith("/SKILL.md"):
        relative = relative[: -len("/SKILL.md")]
    return relative or name


def _standalone_web_fast_path(message: str) -> str | None:
    """Classify fully-scoped vanilla web artifacts without invoking a planner."""
    if not (_STANDALONE_ACTION_RE.search(message) and _STANDALONE_WEB_RE.search(message)):
        return None
    return (
        "Fast-path: this is a single standalone HTML/CSS/JS artifact. "
        "Do not load skills and do not call `simplicio plan` or `simplicio run`. "
        "Use one `simplicio edit --plan` for the decided file, then run focused "
        "syntax/browser checks and `simplicio validate`; return compact receipts."
    )


@lru_cache(maxsize=1)
def _catalog() -> tuple[tuple[str, frozenset[str], frozenset[str], str], ...]:
    if not DB_PATH.exists():
        return ()
    connection = sqlite3.connect(DB_PATH, timeout=0.25)
    try:
        rows = connection.execute(
            """
            SELECT sr.skill_name,
                   COALESCE(mi.title, sr.skill_name) || ' ' || COALESCE(mi.content, ''),
                   COALESCE(sr.artifact_path, mi.artifact_path, '')
              FROM skills_registry sr
              LEFT JOIN memory_items mi ON mi.stable_id = sr.stable_id
             WHERE sr.enabled = 1
            """
        ).fetchall()
    finally:
        connection.close()
    return tuple(
        (
            _canonical_skill_handle(name, path),
            frozenset(_tokens(name)),
            frozenset(_tokens(searchable)),
            path,
        )
        for name, searchable, path in rows
    )


def recall(message: str, k: int = TOP_K) -> list[tuple[str, float, str]]:
    query = _expanded_query(message)
    if not query or query <= _TRIVIAL:
        return []
    ranked: list[tuple[str, float, str]] = []
    seen: set[str] = set()
    for name, name_tokens, text_tokens, path in _catalog():
        if name in seen:
            continue
        overlap = query & text_tokens
        name_overlap = query & name_tokens
        if not overlap and not name_overlap:
            continue
        score = (2.4 * len(name_overlap)) + (1.0 * len(overlap))
        score /= math.sqrt(max(1, len(query)))
        if _norm(name.split("/")[-1]).replace("-", " ") in _norm(message):
            score += 2.0
        if score >= MIN_SCORE:
            ranked.append((name, score, path))
            seen.add(name)
    ranked.sort(key=lambda item: (-item[1], item[0]))
    return ranked[:k]


def _record(skill_name: str, event: str, detail: str = "") -> None:
    if not DB_PATH.exists():
        return
    try:
        connection = sqlite3.connect(DB_PATH, timeout=0.25)
        with connection:
            connection.execute(
                "INSERT INTO skill_load_events(skill_name,event,detail) VALUES(?,?,?)",
                (skill_name, event, detail[:500]),
            )
        connection.close()
    except sqlite3.Error:
        return


def _adaptive_hits(hits: list[tuple[str, float, str]]) -> list[tuple[str, float, str]]:
    if len(hits) <= 1:
        return hits
    lead = hits[0][1]
    gap = lead - hits[1][1]
    if lead >= 2.0 and gap >= 0.75:
        return hits[:1]
    if lead >= 1.5 and gap >= 0.30:
        return hits[:2]
    return hits[:3]


def _pre_llm_call(**kwargs: Any) -> dict[str, str] | None:
    if _disabled():
        return None
    message = str(kwargs.get("user_message") or "").strip()
    fast_path = _standalone_web_fast_path(message)
    if fast_path:
        return {"context": fast_path}
    hits = _adaptive_hits(recall(message))
    if not hits:
        return None
    handles = ", ".join(f"`{name}`" for name, _score, _path in hits)
    return {
        "context": f"Skill recall: {handles}. Load only applicable candidates with skill_view."
    }


def _post_tool_call(**kwargs: Any) -> None:
    if _disabled() or kwargs.get("tool_name") != "skill_view":
        return
    args = kwargs.get("args") or {}
    name = str(args.get("name") or "").strip()
    if not name:
        return
    result = str(kwargs.get("result") or "")
    event = "loaded" if '"success": true' in result.lower() or "success: true" in result.lower() else "error"
    _record(name, event, f"session={kwargs.get('session_id', '')}; task={kwargs.get('task_id', '')}")


def register_skill_recall(ctx: Any) -> None:
    ctx.register_hook("pre_llm_call", _pre_llm_call)
    ctx.register_hook("post_tool_call", _post_tool_call)
