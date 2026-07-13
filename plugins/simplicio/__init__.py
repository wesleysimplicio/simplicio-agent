from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from .skill_recall import register_skill_recall

_MANAGED_REPO_NAMES = {"simplicio-agent", "simplicio-runtime"}
_PATH_ARG_KEYS = (
    "path",
    "file_path",
    "repo",
    "workdir",
    "target",
)

# ---------------------------------------------------------------------------
# Hermes-native-first policy (issue #100)
#
# Stable, codified guidance -- not just conversational convention -- for
# which surface handles which kind of work:
#
#   1. Read / search / analyze -> native Hermes tools (`read_file`,
#      `search_files`, grep-style tools, etc.). This is orientation work:
#      cheapest, fastest, no repo lock-in, and it's what Hermes is already
#      good at.
#   2. Mutate / validate / checkpoint -> Simplicio-runtime (`simplicio edit`,
#      `simplicio dev-cli`, `simplicio validate`, `simplicio checkpoints`,
#      ...). Deterministic, evidence-producing, and -- for managed repos --
#      the *only* path `_on_pre_tool_call` below allows for writes.
#   3. Native fallback is an explicit EXCEPTION, not a silent substitute:
#      only when the runtime doesn't cover something yet, and the gap
#      should be logged (an issue) so the runtime grows to close it.
#
# This is the *task-type* axis (read vs. mutate). It composes with, and
# deliberately does not restate, AGENTS.md "Tool routing" (issue #212),
# which governs the *channel* axis (Simplicio CLI is the primary execution
# surface, MCP is fallback transport only) once you've already decided to
# mutate. See AGENTS.md#tool-routing for that piece.
# ---------------------------------------------------------------------------
HERMES_NATIVE_FIRST_POLICY = (
    "Hermes-native-first: read/search/analyze with native Hermes tools; "
    "mutate/validate/checkpoint through the Simplicio-runtime; fall back to "
    "native tools only as an explicit exception when the runtime has a gap "
    "(and log that gap so the runtime can close it)."
)

_TOOL_GUIDANCE = {
    "write_file": "Prefer Hermes native `read_file`/`search_files` first for orientation, then use `simplicio edit --plan ... --repo <repo>` or `simplicio dev-cli \"<task>\" --repo <repo>` for writes, validation, and checkpoints.",
    "patch": "Prefer Hermes native `read_file`/`search_files` first for orientation, then use `simplicio edit --plan ... --repo <repo>` or `simplicio dev-cli \"<task>\" --repo <repo>` for writes, validation, and checkpoints.",
}
_BLOCKED_TOOLS = frozenset(_TOOL_GUIDANCE)


def _plugin_disabled() -> bool:
    return os.environ.get("SIMPLICIO_PLUGIN_DISABLE", "").strip().lower() in {"1", "true", "yes", "on"}


def _managed_repo_roots() -> list[Path]:
    home = Path.home()
    base = home / "Projetos" / "ai"
    return [base / "simplicio-agent", base / "simplicio-runtime"]


def _iter_candidate_paths(args: Dict[str, Any]) -> Iterable[Path]:
    for key in _PATH_ARG_KEYS:
        raw = args.get(key)
        if not isinstance(raw, str) or not raw.strip():
            continue
        text = raw.strip()
        p = Path(text).expanduser()
        if not p.is_absolute():
            p = (Path.cwd() / p).resolve(strict=False)
        else:
            p = p.resolve(strict=False)
        yield p


def _repo_for_path(path: Path) -> Optional[Path]:
    try:
        resolved = path.resolve(strict=False)
    except Exception:
        resolved = path
    for root in _managed_repo_roots():
        try:
            root_resolved = root.resolve(strict=False)
            resolved.relative_to(root_resolved)
            return root_resolved
        except Exception:
            continue
    parts = set(resolved.parts)
    if _MANAGED_REPO_NAMES & parts:
        for root in _managed_repo_roots():
            if root.name in parts:
                return root.resolve(strict=False)
    return None


def _target_repo(args: Dict[str, Any]) -> Optional[Path]:
    for candidate in _iter_candidate_paths(args):
        repo = _repo_for_path(candidate)
        if repo is not None:
            return repo
    return None


def _block_message(tool_name: str, repo: Path) -> str:
    repo_str = str(repo)
    guidance = _TOOL_GUIDANCE.get(tool_name, "Use terminal + `simplicio ... --repo <repo>` instead.").replace("<repo>", repo_str)
    return (
        f"simplicio plugin blocked native Hermes tool `{tool_name}` inside managed repo `{repo_str}`. "
        "This repo must be operated through the Simplicio runtime. "
        f"{guidance} "
        f"Canonical orient command: `simplicio runtime map --repo {repo_str} --for-llm markdown`. "
        f"Policy: {HERMES_NATIVE_FIRST_POLICY}"
    )


def _on_pre_tool_call(tool_name: str = "", args: Any = None, **_: Any) -> Optional[Dict[str, str]]:
    if _plugin_disabled() or tool_name not in _BLOCKED_TOOLS or not isinstance(args, dict):
        return None
    repo = _target_repo(args)
    if repo is None:
        return None
    return {"action": "block", "message": _block_message(tool_name, repo)}


# ---------------------------------------------------------------------------
# Watcher PID pattern (Asolaria N-Nest-Prime, issue #17 P0 #1)
#
# `_on_pre_tool_call` above forces every write inside a managed repo through
# the terminal (`simplicio edit` / `simplicio dev-cli`), which means the
# native `_turn_file_mutation_paths` verifier (run_agent.py) never sees
# these edits at all -- it only tracks the native write_file/patch tools
# this very plugin blocks. So the "did the edit actually land" check needs
# its own, independent watcher here, at the one place that reliably sees
# every terminal command AND its real output: `transform_terminal_output`.
#
# The watcher is a genuinely separate recompute, not a reminder for the
# same agent to redo its own check: it runs `simplicio validate --repo
# <repo>` itself, via subprocess, and appends the real PASS/FAIL result to
# the terminal tool's own output -- "child.reported == watcher.recomputed_
# truth" from N-Nest-Prime, applied to a real deterministic CLI instead of
# a second LLM call. An unavailable `simplicio` binary is reported
# honestly (no silent fake pass), matching AGENTS.md "no silent fake data".
# ---------------------------------------------------------------------------

_EDIT_CMD_RE = re.compile(r"(?<![\w-])simplicio\s+(?:edit|dev-cli)\b")
_VALIDATE_CMD_RE = re.compile(r"(?<![\w-])simplicio\s+validate\b")
_REPO_FLAG_RE = re.compile(r"--repo[=\s]+(\S+)")

# Bound the watcher's own subprocess -- it must never hang the terminal
# tool call it's piggybacking on.
_WATCHER_VALIDATE_TIMEOUT_S = 120
_WATCHER_OUTPUT_TAIL_CHARS = 800


def _strip_quotes(raw: str) -> str:
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in ("'", '"'):
        return raw[1:-1]
    return raw


def _repo_from_command(command: str) -> Optional[Path]:
    """Resolve the target repo for a `simplicio edit`/`dev-cli` invocation.

    Prefers an explicit `--repo <path>` flag on the command line; falls
    back to the process cwd (the common case: the model already `cd`'d
    into the managed repo before running `simplicio edit`).
    """
    m = _REPO_FLAG_RE.search(command or "")
    if m:
        raw = _strip_quotes(m.group(1).strip())
        p = Path(raw).expanduser()
        if not p.is_absolute():
            p = (Path.cwd() / p).resolve(strict=False)
        else:
            p = p.resolve(strict=False)
        return _repo_for_path(p) or (p if p.name in _MANAGED_REPO_NAMES else None)
    return _repo_for_path(Path.cwd())


def _run_watcher_validate(repo: Path) -> str:
    """Independently recompute: run `simplicio validate --repo <repo>`.

    Never fakes a pass. An unavailable binary or a subprocess error
    surfaces as an explicit, honest watcher note instead of silence.
    """
    binary = shutil.which("simplicio")
    if not binary:
        return (
            "[watcher] simplicio binary not found on PATH -- could NOT "
            "independently verify this edit. Run `simplicio validate "
            f"--repo {repo}` manually before considering it done."
        )
    try:
        proc = subprocess.run(
            [binary, "validate", "--repo", str(repo)],
            capture_output=True,
            text=True,
            timeout=_WATCHER_VALIDATE_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        return (
            f"[watcher] simplicio validate --repo {repo} timed out after "
            f"{_WATCHER_VALIDATE_TIMEOUT_S}s -- could NOT independently verify "
            "this edit."
        )
    except Exception as exc:  # noqa: BLE001 - watcher must never raise into the terminal tool
        return f"[watcher] simplicio validate --repo {repo} failed to run: {exc}"

    status = "PASS" if proc.returncode == 0 else "FAIL"
    tail = (proc.stdout or "") + (proc.stderr or "")
    tail = tail.strip()[-_WATCHER_OUTPUT_TAIL_CHARS:]
    return (
        f"[watcher] independent verification: `simplicio validate --repo {repo}` "
        f"-> {status} (exit {proc.returncode})\n{tail}"
    ).rstrip()


def _on_transform_terminal_output(
    command: str = "", output: str = "", returncode: int = 0, **_: Any
) -> Optional[str]:
    if _plugin_disabled() or not isinstance(command, str):
        return None
    if _VALIDATE_CMD_RE.search(command):
        # This IS the validate call -- never recurse into re-validating it.
        return None
    if not _EDIT_CMD_RE.search(command):
        return None
    repo = _repo_from_command(command)
    if repo is None:
        return None
    watcher_note = _run_watcher_validate(repo)
    return f"{output}\n\n{watcher_note}"


def register(ctx) -> None:
    ctx.register_hook("pre_tool_call", _on_pre_tool_call)
    ctx.register_hook("transform_terminal_output", _on_transform_terminal_output)
    register_skill_recall(ctx)
