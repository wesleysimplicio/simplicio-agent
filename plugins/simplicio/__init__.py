from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

_MANAGED_REPO_NAMES = {"simplicio-agent", "simplicio-runtime"}
_PATH_ARG_KEYS = (
    "path",
    "file_path",
    "repo",
    "workdir",
    "target",
)
_TOOL_GUIDANCE = {
    "read_file": "Use terminal + `simplicio runtime map --repo <repo> --for-llm markdown` or `simplicio map --repo <repo> --json` first.",
    "search_files": "Use terminal + `simplicio runtime map --repo <repo> --for-llm markdown`, `simplicio orientation pack --repo <repo> --json`, or `simplicio map --repo <repo> --json` first.",
    "write_file": "Use terminal + `simplicio edit --plan ... --repo <repo>` or `simplicio dev-cli \"<task>\" --repo <repo>` for writes.",
    "patch": "Use terminal + `simplicio edit --plan ... --repo <repo>` or `simplicio dev-cli \"<task>\" --repo <repo>` for writes.",
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
        f"Canonical orient command: `simplicio runtime map --repo {repo_str} --for-llm markdown`."
    )


def _on_pre_tool_call(tool_name: str = "", args: Any = None, **_: Any) -> Optional[Dict[str, str]]:
    if _plugin_disabled() or tool_name not in _BLOCKED_TOOLS or not isinstance(args, dict):
        return None
    repo = _target_repo(args)
    if repo is None:
        return None
    return {"action": "block", "message": _block_message(tool_name, repo)}


def register(ctx) -> None:
    ctx.register_hook("pre_tool_call", _on_pre_tool_call)
