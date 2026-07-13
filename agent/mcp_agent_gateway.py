"""External-LLM gateway for the Simplicio Agent MCP server.

External clients submit intent to the Agent. The Agent reasons and coordinates;
the compiled Simplicio Runtime ranks capabilities and performs execution. The
public MCP surface stays small so clients do not pay prompt tokens for the
Runtime's full command catalog.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

DEFAULT_MODE = "fast:fast"
DEFAULT_TIMEOUT_SECONDS = 900
MAX_TIMEOUT_SECONDS = 1800
MAX_OUTPUT_CHARS = 30_000


def _resolve_workdir(workdir: str | None) -> Path:
    candidate = Path(workdir or os.getcwd()).expanduser().resolve()
    if not candidate.is_dir():
        raise ValueError(f"workdir is not an existing directory: {candidate}")
    return candidate


def _binary(name: str) -> str:
    resolved = shutil.which(name)
    if not resolved:
        raise RuntimeError(f"required executable is unavailable: {name}")
    return resolved


def _last_json_object(text: str) -> dict[str, Any]:
    for line in reversed(text.splitlines()):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise ValueError("command returned no JSON object")


def _bounded(value: int, *, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, int(value)))


def rank_capabilities(
    request: str,
    *,
    workdir: str | None = None,
    limit: int = 5,
) -> dict[str, Any]:
    """Return compact Helo-ranked capability metadata for an external intent."""
    query = (request or "").strip()
    if not query:
        return {"success": False, "error": "request is required", "mode": DEFAULT_MODE}

    try:
        repo = _resolve_workdir(workdir)
        completed = subprocess.run(
            [
                _binary("simplicio"),
                "capabilities",
                "rank",
                query,
                "--repo",
                str(repo),
                "--json",
            ],
            cwd=repo,
            text=True,
            capture_output=True,
            timeout=120,
            check=False,
        )
        if completed.returncode != 0:
            return {
                "success": False,
                "error": "runtime capability recall failed",
                "exit_code": completed.returncode,
                "stderr": completed.stderr[-2000:],
                "mode": DEFAULT_MODE,
            }
        payload = _last_json_object(completed.stdout)
    except (OSError, subprocess.TimeoutExpired, RuntimeError, ValueError) as exc:
        return {"success": False, "error": str(exc), "mode": DEFAULT_MODE}

    selected = []
    for item in payload.get("selected", [])[: _bounded(limit, minimum=1, maximum=10)]:
        capability = item.get("capability") or {}
        selected.append(
            {
                "id": capability.get("id"),
                "kind": capability.get("kind"),
                "pack": capability.get("pack"),
                "status": capability.get("status"),
                "reason": item.get("reason"),
                "examples": (capability.get("example_invocations") or [])[:1],
            }
        )

    return {
        "success": True,
        "schema": "simplicio.agent-capability-recall/v1",
        "mode": DEFAULT_MODE,
        "request": query,
        "workdir": str(repo),
        "selected": selected,
    }


def invoke_agent(
    request: str,
    *,
    workdir: str | None = None,
    client: str = "mcp",
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Execute an external request through a real autonomous Agent session."""
    query = (request or "").strip()
    if not query:
        return {"success": False, "error": "request is required", "mode": DEFAULT_MODE}

    try:
        repo = _resolve_workdir(workdir)
    except ValueError as exc:
        return {"success": False, "error": str(exc), "mode": DEFAULT_MODE}

    recall = rank_capabilities(query, workdir=str(repo), limit=5)
    handles = [item.get("id") for item in recall.get("selected", []) if item.get("id")]
    prompt = (
        "External MCP client request. Act autonomously and finish with real evidence. "
        "Hermes/Simplicio Agent reasons and coordinates; all executable actions must "
        "go through the Simplicio Runtime per ADR-0010. "
        f"Client={client}; mode={DEFAULT_MODE}; workdir={repo}. "
        f"Helo capability hints={handles or ['runtime-recall-unavailable']}.\n\n"
        f"REQUEST:\n{query}"
    )
    timeout = _bounded(timeout_seconds, minimum=30, maximum=MAX_TIMEOUT_SECONDS)
    command = [
        _binary("simplicio-agent"),
        "chat",
        "-q",
        prompt,
        "-Q",
        "--source",
        "tool",
        "--yolo",
        "--max-turns",
        "90",
    ]

    started = time.perf_counter()
    try:
        completed = subprocess.run(
            command,
            cwd=repo,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired, RuntimeError) as exc:
        return {
            "success": False,
            "error": str(exc),
            "mode": DEFAULT_MODE,
            "capabilities": handles,
        }

    elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
    stdout = completed.stdout[-MAX_OUTPUT_CHARS:]
    stderr = completed.stderr[-4000:]
    return {
        "success": completed.returncode == 0,
        "schema": "simplicio.agent-action-result/v1",
        "mode": DEFAULT_MODE,
        "autonomy": "yolo",
        "client": client,
        "workdir": str(repo),
        "capabilities": handles,
        "exit_code": completed.returncode,
        "elapsed_ms": elapsed_ms,
        "output": stdout,
        "stderr": stderr if completed.returncode else "",
        "truncated": len(completed.stdout) > MAX_OUTPUT_CHARS,
    }
