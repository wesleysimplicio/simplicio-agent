"""Shared slash command helpers for skills.

Shared between CLI (cli.py) and gateway (gateway/run.py) so both surfaces
can invoke skills via /skill-name commands.
"""

import copy
import json
import logging
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

from hermes_constants import display_hermes_home
from agent.skill_preprocessing import (
    expand_inline_shell as _expand_inline_shell,
    load_skills_config as _load_skills_config,
    substitute_template_vars as _substitute_template_vars,
)

logger = logging.getLogger(__name__)

_skill_commands: Dict[str, Dict[str, Any]] = {}
_skill_commands_platform: Optional[str] = None
_skill_payload_cache: Dict[tuple[Optional[str], str, str], tuple[float, tuple[dict[str, Any], Path | None, str]]] = {}
_skill_payload_cache_inflight: set[tuple[Optional[str], str, str]] = set()
_skill_payload_cache_lock = threading.Lock()
_SKILL_PAYLOAD_CACHE_TTL_SECONDS = 300.0
_SKILL_PAYLOAD_INFLIGHT_WAIT_SECONDS = 0.35
# Prewarming is best-effort and must not turn a large skills catalog into an
# unbounded background workload or resident cache. Config values are clamped
# by hard ceilings so an oversized config cannot undo the safety bound.
_SKILL_PREWARM_MAX_ITEMS_DEFAULT = 8
_SKILL_PREWARM_MAX_ITEMS_HARD = 32
_SKILL_PAYLOAD_CACHE_MAX_ENTRIES_DEFAULT = 64
_SKILL_PAYLOAD_CACHE_MAX_ENTRIES_HARD = 256
# Patterns for sanitizing skill names into clean hyphen-separated slugs.
_SKILL_INVALID_CHARS = re.compile(r"[^a-z0-9-]")
_SKILL_MULTI_HYPHEN = re.compile(r"-{2,}")

# ---------------------------------------------------------------------------
# Skill-scaffolding markers and the canonical extractor.
#
# When a user invokes a /skill (or /bundle), Hermes expands the turn into a
# model-facing message that embeds the full skill body plus scaffolding. That
# expanded text is what flows into the agent loop — and into memory providers
# via MemoryManager. Providers that store or embed the raw user turn (mem0,
# openviking, hindsight, retaindb, byterover, honcho, supermemory) would
# otherwise capture the entire skill body instead of what the user actually
# asked. ``extract_user_instruction_from_skill_message`` recovers just the
# user's instruction so memory stays clean.
#
# These markers MUST stay byte-identical to the builders below
# (``_build_skill_message`` here, ``build_bundle_invocation_message`` in
# agent/skill_bundles.py). They are co-located with the single-skill builder
# on purpose, and the bundle markers are asserted against the bundle builder in
# tests/openviking_plugin/test_openviking.py::test_skill_markers_match_hermes_scaffolding.
# ---------------------------------------------------------------------------
_SKILL_INVOCATION_PREFIX = "[IMPORTANT: The user has invoked the "
_SINGLE_SKILL_MARKER = "The full skill content is loaded below.]"
_SINGLE_SKILL_INSTRUCTION = (
    "The user has provided the following instruction alongside the skill invocation: "
)
_RUNTIME_NOTE = "\n\n[Runtime note:"
_BUNDLE_MARKER = " skill bundle,"
_BUNDLE_USER_INSTRUCTION = "\nUser instruction: "
_BUNDLE_FIRST_SKILL_BLOCK = "\n\n[Loaded as part of the "


def extract_user_instruction_from_skill_message(content: Any) -> Optional[str]:
    """Recover the user's instruction from a slash-skill-expanded turn.

    Returns:
        - The original string unchanged when it is NOT skill scaffolding
          (a normal user message passes straight through).
        - The extracted user instruction when the scaffolding carried one.
        - ``None`` when the content is skill scaffolding with no user
          instruction (i.e. a bare ``/skill`` invocation). Callers that feed
          memory providers should skip the turn in that case — there is no
          user content worth storing.
    """
    if not isinstance(content, str):
        return None

    if not content.startswith(_SKILL_INVOCATION_PREFIX):
        return content

    if _BUNDLE_MARKER in content:
        return _extract_bundle_user_instruction(content)

    if _SINGLE_SKILL_MARKER in content:
        return _extract_single_skill_user_instruction(content)

    return None


def _extract_single_skill_user_instruction(message: str) -> Optional[str]:
    # Single-skill format appends the user instruction after the skill body, so
    # the last occurrence is the user-provided one; the body may quote this text.
    marker_idx = message.rfind(_SINGLE_SKILL_INSTRUCTION)
    if marker_idx < 0:
        return None

    instruction = message[marker_idx + len(_SINGLE_SKILL_INSTRUCTION):]
    runtime_idx = instruction.find(_RUNTIME_NOTE)
    if runtime_idx >= 0:
        instruction = instruction[:runtime_idx]
    instruction = instruction.strip()
    return instruction or None


def _extract_bundle_user_instruction(message: str) -> Optional[str]:
    # Bundle format puts the user instruction before the loaded skills, so the
    # first occurrence is the user-provided one.
    marker_idx = message.find(_BUNDLE_USER_INSTRUCTION)
    if marker_idx < 0:
        return None

    instruction = message[marker_idx + len(_BUNDLE_USER_INSTRUCTION):]
    first_skill_idx = instruction.find(_BUNDLE_FIRST_SKILL_BLOCK)
    if first_skill_idx >= 0:
        instruction = instruction[:first_skill_idx]
    instruction = instruction.strip()
    return instruction or None


def _resolve_skill_commands_platform() -> Optional[str]:
    """Return the current platform scope used for disabled-skill filtering.

    Used to detect when the active platform has shifted so
    :func:`get_skill_commands` can drop a stale cache that was populated
    for a different platform's ``skills.platform_disabled`` view (#14536).

    Resolves from (in order) ``HERMES_PLATFORM`` env var and
    ``HERMES_SESSION_PLATFORM`` from the gateway session context. Returns
    ``None`` when no platform scope is active (e.g. classic CLI, RL
    rollouts, standalone scripts).
    """
    try:
        from gateway.session_context import get_session_env

        resolved_platform = (
            os.getenv("HERMES_PLATFORM")
            or get_session_env("HERMES_SESSION_PLATFORM")
        )
    except Exception:
        resolved_platform = os.getenv("HERMES_PLATFORM")
    return resolved_platform or None

def _normalize_skill_identifier(raw_identifier: str) -> str | None:
    raw_identifier = (raw_identifier or "").strip()
    if not raw_identifier:
        return None

    from tools.skills_tool import SKILLS_DIR
    from agent.skill_utils import get_external_skills_dirs

    identifier_path = Path(raw_identifier).expanduser()
    if not identifier_path.is_absolute():
        return raw_identifier.lstrip("/")

    normalized = None
    trusted_roots = [SKILLS_DIR]
    try:
        trusted_roots.extend(get_external_skills_dirs())
    except Exception:
        pass

    for root in trusted_roots:
        try:
            normalized = str(identifier_path.relative_to(root))
            break
        except ValueError:
            continue

    if normalized is None:
        try:
            normalized = str(identifier_path.resolve().relative_to(SKILLS_DIR.resolve()))
        except Exception:
            normalized = raw_identifier
    return normalized


def _read_skill_payload_uncached(skill_identifier: str, task_id: str | None = None) -> tuple[dict[str, Any], Path | None, str] | None:
    raw_identifier = (skill_identifier or "").strip()
    normalized = _normalize_skill_identifier(raw_identifier)
    if not normalized:
        return None

    try:
        from tools.skills_tool import SKILLS_DIR, skill_view

        loaded_skill = json.loads(
            skill_view(normalized, task_id=task_id, preprocess=False)
        )
    except Exception:
        return None

    if not loaded_skill.get("success"):
        return None

    skill_name = str(loaded_skill.get("name") or normalized)
    skill_path = str(loaded_skill.get("path") or "")
    skill_dir = None
    abs_skill_dir = loaded_skill.get("skill_dir")
    if abs_skill_dir:
        skill_dir = Path(abs_skill_dir)
    elif skill_path:
        try:
            skill_dir = SKILLS_DIR / Path(skill_path).parent
        except Exception:
            skill_dir = None

    return loaded_skill, skill_dir, skill_name


def _skill_payload_cache_key(skill_identifier: str) -> tuple[Optional[str], str, str] | None:
    normalized = _normalize_skill_identifier(skill_identifier)
    if not normalized:
        return None
    # Scope the cache key to the current SKILLS_DIR: without this, two skills
    # sharing a name but living under different roots (a real scenario when
    # ``--skills-dir``/per-project overrides change SKILLS_DIR at runtime, and
    # an observed test-isolation hazard when tests monkeypatch SKILLS_DIR to a
    # fresh tmp dir per test) collide on the same cache entry and one serves
    # the other's stale payload for up to _SKILL_PAYLOAD_CACHE_TTL_SECONDS.
    try:
        from tools.skills_tool import SKILLS_DIR
        skills_dir_key = str(SKILLS_DIR)
    except Exception:
        skills_dir_key = ""
    return (_resolve_skill_commands_platform(), skills_dir_key, normalized)


def invalidate_skill_payload_cache(skill_identifier: str | None = None) -> None:
    with _skill_payload_cache_lock:
        if skill_identifier is None:
            _skill_payload_cache.clear()
            _skill_payload_cache_inflight.clear()
            return
        key = _skill_payload_cache_key(skill_identifier)
        if key is None:
            return
        _skill_payload_cache.pop(key, None)
        _skill_payload_cache_inflight.discard(key)


def _bounded_skills_config_int(
    key: str,
    default: int,
    maximum: int,
    minimum: int = 0,
) -> int:
    """Read one bounded skills setting without making config a hot import."""
    try:
        value = int(_load_skills_config().get(key, default))
    except (TypeError, ValueError, AttributeError):
        value = default
    return min(max(value, minimum), maximum)


def _skill_payload_cache_limit() -> int:
    return _bounded_skills_config_int(
        "prewarm_cache_max_entries",
        _SKILL_PAYLOAD_CACHE_MAX_ENTRIES_DEFAULT,
        _SKILL_PAYLOAD_CACHE_MAX_ENTRIES_HARD,
        minimum=1,
    )


def _store_skill_payload_cache(
    key: tuple[Optional[str], str],
    payload: tuple[dict[str, Any], Path | None, str],
) -> None:
    """Store a payload and evict oldest entries beyond the bounded cache."""
    cache_limit = _skill_payload_cache_limit()
    with _skill_payload_cache_lock:
        _skill_payload_cache[key] = (time.time(), payload)
        while len(_skill_payload_cache) > cache_limit:
            _skill_payload_cache.pop(next(iter(_skill_payload_cache)))


def _wait_for_inflight_skill_payload(
    key: tuple[Optional[str], str],
    timeout_seconds: float = _SKILL_PAYLOAD_INFLIGHT_WAIT_SECONDS,
) -> tuple[dict[str, Any], Path | None, str] | None:
    deadline = time.time() + max(timeout_seconds, 0.0)
    while time.time() < deadline:
        with _skill_payload_cache_lock:
            cached = _skill_payload_cache.get(key)
            if cached and (time.time() - cached[0]) < _SKILL_PAYLOAD_CACHE_TTL_SECONDS:
                return copy.deepcopy(cached[1])
            if key not in _skill_payload_cache_inflight:
                return None
        time.sleep(0.01)
    return None


def prewarm_skill_payloads(skill_identifiers: list[str] | tuple[str, ...]) -> None:
    keys_to_warm: list[tuple[Optional[str], str, str]] = []
    max_items = _bounded_skills_config_int(
        "prewarm_max_items",
        _SKILL_PREWARM_MAX_ITEMS_DEFAULT,
        _SKILL_PREWARM_MAX_ITEMS_HARD,
    )
    if max_items <= 0:
        return

    now = time.time()
    with _skill_payload_cache_lock:
        for index, identifier in enumerate(skill_identifiers or []):
            if index >= max_items:
                break
            key = _skill_payload_cache_key(identifier)
            if key is None:
                continue
            cached = _skill_payload_cache.get(key)
            if cached and (now - cached[0]) < _SKILL_PAYLOAD_CACHE_TTL_SECONDS:
                continue
            if key in _skill_payload_cache_inflight:
                continue
            _skill_payload_cache_inflight.add(key)
            keys_to_warm.append(key)

    if not keys_to_warm:
        return

    def _worker() -> None:
        for key in keys_to_warm:
            # key is (platform, skills_dir, normalized_identifier) — see
            # _skill_payload_cache_key. Only the last element is needed here.
            normalized = key[-1]
            try:
                payload = _read_skill_payload_uncached(normalized)
                if payload is not None:
                    _store_skill_payload_cache(key, payload)
            except Exception:
                pass
            finally:
                with _skill_payload_cache_lock:
                    _skill_payload_cache_inflight.discard(key)

    threading.Thread(target=_worker, name="skills-prewarm", daemon=True).start()


def _load_skill_payload(skill_identifier: str, task_id: str | None = None) -> tuple[dict[str, Any], Path | None, str] | None:
    """Load a skill by name/path and return (loaded_payload, skill_dir, display_name)."""
    key = _skill_payload_cache_key(skill_identifier)
    if key is None:
        return None

    now = time.time()
    with _skill_payload_cache_lock:
        cached = _skill_payload_cache.get(key)
        if cached and (now - cached[0]) < _SKILL_PAYLOAD_CACHE_TTL_SECONDS:
            return copy.deepcopy(cached[1])
        inflight = key in _skill_payload_cache_inflight
        if not inflight:
            _skill_payload_cache_inflight.add(key)

    if inflight:
        warmed = _wait_for_inflight_skill_payload(key)
        if warmed is not None:
            return warmed

    payload = _read_skill_payload_uncached(skill_identifier, task_id=task_id)
    if payload is None:
        with _skill_payload_cache_lock:
            _skill_payload_cache_inflight.discard(key)
        return None

    _store_skill_payload_cache(key, payload)
    with _skill_payload_cache_lock:
        _skill_payload_cache_inflight.discard(key)
    return copy.deepcopy(payload)

def _inject_skill_config(loaded_skill: dict[str, Any], parts: list[str]) -> None:
    """Resolve and inject skill-declared config values into the message parts.

    If the loaded skill's frontmatter declares ``metadata.hermes.config``
    entries, their current values (from config.yaml or defaults) are appended
    as a ``[Skill config: ...]`` block so the agent knows the configured values
    without needing to read config.yaml itself.
    """
    try:
        from agent.skill_utils import (
            extract_skill_config_vars,
            parse_frontmatter,
            resolve_skill_config_values,
        )

        # The loaded_skill dict contains the raw content which includes frontmatter
        raw_content = str(loaded_skill.get("raw_content") or loaded_skill.get("content") or "")
        if not raw_content:
            return

        frontmatter, _ = parse_frontmatter(raw_content)
        config_vars = extract_skill_config_vars(frontmatter)
        if not config_vars:
            return

        resolved = resolve_skill_config_values(config_vars)
        if not resolved:
            return

        lines = ["", f"[Skill config (from {display_hermes_home()}/config.yaml):"]
        for key, value in resolved.items():
            display_val = str(value) if value else "(not set)"
            lines.append(f"  {key} = {display_val}")
        lines.append("]")
        parts.extend(lines)
    except Exception:
        pass  # Non-critical — skill still loads without config injection


def _build_skill_message(
    loaded_skill: dict[str, Any],
    skill_dir: Path | None,
    activation_note: str,
    user_instruction: str = "",
    runtime_note: str = "",
    session_id: str | None = None,
) -> str:
    """Format a loaded skill into a user/system message payload."""
    from tools.skills_tool import SKILLS_DIR

    content = str(loaded_skill.get("content") or "")

    # ── Template substitution and inline-shell expansion ──
    # Done before anything else so downstream blocks (setup notes,
    # supporting-file hints) see the expanded content.
    skills_cfg = _load_skills_config()
    if skills_cfg.get("template_vars", True):
        content = _substitute_template_vars(content, skill_dir, session_id)
    if skills_cfg.get("inline_shell", False):
        timeout = int(skills_cfg.get("inline_shell_timeout", 10) or 10)
        content = _expand_inline_shell(content, skill_dir, timeout)

    parts = [activation_note, "", content.strip()]

    # ── Inject the absolute skill directory so the agent can reference
    #    bundled scripts without an extra skill_view() round-trip. ──
    if skill_dir:
        parts.append("")
        parts.append(f"[Skill directory: {skill_dir}]")
        parts.append(
            "Resolve any relative paths in this skill (e.g. `scripts/foo.js`, "
            "`templates/config.yaml`) against that directory, then run them "
            "with the terminal tool using the absolute path."
        )

    # ── Inject resolved skill config values ──
    _inject_skill_config(loaded_skill, parts)

    if loaded_skill.get("setup_skipped"):
        parts.extend(
            [
                "",
                "[Skill setup note: Required environment setup was skipped. Continue loading the skill and explain any reduced functionality if it matters.]",
            ]
        )
    elif loaded_skill.get("gateway_setup_hint"):
        parts.extend(
            [
                "",
                f"[Skill setup note: {loaded_skill['gateway_setup_hint']}]",
            ]
        )
    elif loaded_skill.get("setup_needed") and loaded_skill.get("setup_note"):
        parts.extend(
            [
                "",
                f"[Skill setup note: {loaded_skill['setup_note']}]",
            ]
        )

    supporting = []
    linked_files = loaded_skill.get("linked_files") or {}
    for entries in linked_files.values():
        if isinstance(entries, list):
            supporting.extend(entries)

    if not supporting and skill_dir:
        for subdir in ("references", "templates", "scripts", "assets"):
            subdir_path = skill_dir / subdir
            if subdir_path.exists():
                for f in sorted(subdir_path.rglob("*")):
                    if f.is_file() and not f.is_symlink():
                        rel = str(f.relative_to(skill_dir))
                        supporting.append(rel)

    if supporting and skill_dir:
        try:
            skill_view_target = str(skill_dir.relative_to(SKILLS_DIR))
        except ValueError:
            # Skill is from an external dir — use the skill name instead
            skill_view_target = skill_dir.name
        parts.append("")
        parts.append("[This skill has supporting files:]")
        for sf in supporting:
            parts.append(f"- {sf}  ->  {skill_dir / sf}")
        parts.append(
            f'\nLoad any of these with skill_view(name="{skill_view_target}", '
            f'file_path="<path>"), or run scripts directly by absolute path '
            f"(e.g. `node {skill_dir}/scripts/foo.js`)."
        )

    if user_instruction:
        parts.append("")
        parts.append(f"The user has provided the following instruction alongside the skill invocation: {user_instruction}")

    if runtime_note:
        parts.append("")
        parts.append(f"[Runtime note: {runtime_note}]")

    return "\n".join(parts)


def scan_skill_commands() -> Dict[str, Dict[str, Any]]:
    """Scan ~/.hermes/skills/ and return a mapping of /command -> skill info.

    Returns:
        Dict mapping "/skill-name" to {name, description, skill_md_path, skill_dir}.
    """
    global _skill_commands, _skill_commands_platform
    _skill_commands_platform = _resolve_skill_commands_platform()
    _skill_commands = {}
    try:
        from tools.skills_tool import SKILLS_DIR, _parse_frontmatter, skill_matches_platform, skill_matches_environment, _get_disabled_skill_names
        from agent.skill_utils import get_external_skills_dirs, iter_skill_index_files
        disabled = _get_disabled_skill_names()
        seen_names: set = set()

        # Scan local dir first, then external dirs
        dirs_to_scan = []
        if SKILLS_DIR.exists():
            dirs_to_scan.append(SKILLS_DIR)
        dirs_to_scan.extend(get_external_skills_dirs())

        for scan_dir in dirs_to_scan:
            for skill_md in iter_skill_index_files(scan_dir, "SKILL.md"):
                if any(part in {'.git', '.github', '.hub', '.archive'} for part in skill_md.parts):
                    continue
                try:
                    content = skill_md.read_text(encoding='utf-8')
                    frontmatter, body = _parse_frontmatter(content)
                    # Skip skills incompatible with the current OS platform
                    if not skill_matches_platform(frontmatter):
                        continue
                    # Skip skills not relevant to the current runtime env
                    # (kanban/docker/s6). Offer-time only; explicit load bypasses.
                    if not skill_matches_environment(frontmatter):
                        continue
                    name = frontmatter.get('name', skill_md.parent.name)
                    if name in seen_names:
                        continue
                    # Respect user's disabled skills config
                    if name in disabled:
                        continue
                    description = frontmatter.get('description', '')
                    if not description:
                        for line in body.strip().split('\n'):
                            line = line.strip()
                            if line and not line.startswith('#'):
                                description = line[:80]
                                break
                    seen_names.add(name)
                    # Normalize to hyphen-separated slug, stripping
                    # non-alnum chars (e.g. +, /) to avoid invalid
                    # Telegram command names downstream.
                    cmd_name = name.lower().replace(' ', '-').replace('_', '-')
                    cmd_name = _SKILL_INVALID_CHARS.sub('', cmd_name)
                    cmd_name = _SKILL_MULTI_HYPHEN.sub('-', cmd_name).strip('-')
                    if not cmd_name:
                        continue
                    _skill_commands[f"/{cmd_name}"] = {
                        "name": name,
                        "description": description or f"Invoke the {name} skill",
                        "skill_md_path": str(skill_md),
                        "skill_dir": str(skill_md.parent),
                    }
                except Exception:
                    continue
    except Exception:
        pass
    return _skill_commands


def get_skill_commands() -> Dict[str, Dict[str, Any]]:
    """Return the current skill commands mapping (scan first if empty).

    Rescans when the active platform scope changes (e.g. a gateway
    process serving Telegram and Discord concurrently) so each platform
    sees its own ``skills.platform_disabled`` view (#14536).
    """
    if (
        not _skill_commands
        or _skill_commands_platform != _resolve_skill_commands_platform()
    ):
        scan_skill_commands()
    return _skill_commands


def reload_skills() -> Dict[str, Any]:
    """Re-scan the skills directory and return a diff of what changed.

    Rescans ``~/.hermes/skills/`` and any ``skills.external_dirs`` so the
    slash-command map (``agent.skill_commands._skill_commands``) reflects
    skills added or removed on disk.

    This does NOT invalidate the skills system-prompt cache. Skills are
    called by name via ``/skill-name``, ``skills_list``, or ``skill_view``
    — they don't need to be in the system prompt for the model to use them.
    Keeping the prompt cache intact preserves prefix caching across the
    reload, so a user invoking ``/reload-skills`` pays no cache-reset cost.

    Returns:
        Dict with keys::

            {
              "added":      [{"name": str, "description": str}, ...],
              "removed":    [{"name": str, "description": str}, ...],
              "unchanged":  [skill names present before and after],
              "total":      total skill count after rescan,
              "commands":   total /slash-skill count after rescan,
            }

        ``description`` is the skill's full SKILL.md frontmatter
        ``description:`` field — the same string the system prompt renders
        as ``    - name: description`` for pre-existing skills.
    """
    # Snapshot pre-reload state (name -> description) from the current
    # slash-command cache. Using dicts lets the post-rescan diff carry
    # descriptions for newly-visible or just-removed skills without a
    # second disk walk.
    def _snapshot(cmds: Dict[str, Dict[str, Any]]) -> Dict[str, str]:
        out: Dict[str, str] = {}
        for slash_key, info in cmds.items():
            bare = slash_key.lstrip("/")
            out[bare] = (info or {}).get("description") or ""
        return out

    before = _snapshot(_skill_commands)

    # Rescan the skills dir. ``scan_skill_commands`` resets
    # ``_skill_commands = {}`` internally and repopulates it.
    new_commands = scan_skill_commands()
    invalidate_skill_payload_cache()

    after = _snapshot(new_commands)

    added_names = sorted(set(after) - set(before))
    removed_names = sorted(set(before) - set(after))
    unchanged = sorted(set(after) & set(before))

    added = [{"name": n, "description": after[n]} for n in added_names]
    # For removed skills, use the description we had cached pre-rescan
    # (the skill file is gone so we can't re-read it).
    removed = [{"name": n, "description": before[n]} for n in removed_names]

    return {
        "added": added,
        "removed": removed,
        "unchanged": unchanged,
        "total": len(after),
        "commands": len(new_commands),
    }


def resolve_skill_command_key(command: str) -> Optional[str]:
    """Resolve a user-typed /command to its canonical skill_cmds key.

    Skills are always stored with hyphens — ``scan_skill_commands`` normalizes
    spaces and underscores to hyphens when building the key. Hyphens and
    underscores are treated interchangeably in user input: this matches
    ``_check_unavailable_skill`` and accommodates Telegram bot-command names
    (which disallow hyphens, so ``/claude-code`` is registered as
    ``/claude_code`` and comes back in the underscored form).

    Returns the matching ``/slug`` key from ``get_skill_commands()`` or
    ``None`` if no match.
    """
    if not command:
        return None
    cmd_key = f"/{command.replace('_', '-')}"
    return cmd_key if cmd_key in get_skill_commands() else None


def build_skill_invocation_message(
    cmd_key: str,
    user_instruction: str = "",
    task_id: str | None = None,
    runtime_note: str = "",
) -> Optional[str]:
    """Build the user message content for a skill slash command invocation.

    Args:
        cmd_key: The command key including leading slash (e.g., "/gif-search").
        user_instruction: Optional text the user typed after the command.

    Returns:
        The formatted message string, or None if the skill wasn't found.
    """
    commands = get_skill_commands()
    skill_info = commands.get(cmd_key)
    if not skill_info:
        return None

    loaded = _load_skill_payload(skill_info["skill_dir"], task_id=task_id)
    if not loaded:
        return None

    loaded_skill, skill_dir, skill_name = loaded

    # Track active usage for Curator lifecycle management (#17782)
    try:
        from tools.skill_usage import bump_use
        bump_use(skill_name)
    except Exception:
        pass  # Non-critical — skill invocation proceeds regardless

    activation_note = (
        f'[IMPORTANT: The user has invoked the "{skill_name}" skill, indicating they want '
        "you to follow its instructions. The full skill content is loaded below.]"
    )
    return _build_skill_message(
        loaded_skill,
        skill_dir,
        activation_note,
        user_instruction=user_instruction,
        runtime_note=runtime_note,
        session_id=task_id,
    )


def build_preloaded_skills_prompt(
    skill_identifiers: list[str],
    task_id: str | None = None,
) -> tuple[str, list[str], list[str]]:
    """Load one or more skills for session-wide CLI preloading.

    Returns (prompt_text, loaded_skill_names, missing_identifiers).
    """
    prompt_parts: list[str] = []
    loaded_names: list[str] = []
    missing: list[str] = []

    seen: set[str] = set()
    for raw_identifier in skill_identifiers:
        identifier = (raw_identifier or "").strip()
        if not identifier or identifier in seen:
            continue
        seen.add(identifier)

        loaded = _load_skill_payload(identifier, task_id=task_id)
        if not loaded:
            missing.append(identifier)
            continue

        loaded_skill, skill_dir, skill_name = loaded

        # Track active usage for Curator lifecycle management (#17782)
        try:
            from tools.skill_usage import bump_use
            bump_use(skill_name)
        except Exception:
            pass  # Non-critical

        activation_note = (
            f'[IMPORTANT: The user launched this CLI session with the "{skill_name}" skill '
            "preloaded. Treat its instructions as active guidance for the duration of this "
            "session unless the user overrides them.]"
        )
        prompt_parts.append(
            _build_skill_message(
                loaded_skill,
                skill_dir,
                activation_note,
                session_id=task_id,
            )
        )
        loaded_names.append(skill_name)

    return "\n\n".join(prompt_parts), loaded_names, missing
