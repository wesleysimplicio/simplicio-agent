"""Tests for ``agent.skill_commands.reload_skills``.

Covers the helper that powers ``/reload-skills`` (CLI + gateway slash command).
The helper rescans the skills directory and returns a diff of what changed.
It does NOT invalidate the skills system-prompt cache — skills are invoked
at runtime via ``/skill-name``, ``skills_list``, or ``skill_view`` and don't
need to live in the system prompt.

``added`` and ``removed`` are lists of ``{"name": str, "description": str}``
dicts. Descriptions are truncated to 60 chars.
"""

import shutil
import tempfile
import textwrap
import time
from pathlib import Path

import pytest


def _write_skill(skills_dir: Path, name: str, description: str = "") -> Path:
    skill_dir = skills_dir / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        textwrap.dedent(
            f"""\
            ---
            name: {name}
            description: {description or f'{name} skill'}
            ---
            body
            """
        )
    )
    return skill_dir


@pytest.fixture
def hermes_home(monkeypatch):
    """Isolate HERMES_HOME for ``reload_skills`` tests.

    Rather than popping cache-bearing modules from ``sys.modules``,
    we monkeypatch the module-level ``HERMES_HOME`` / ``SKILLS_DIR``
    constants in place so the isolation is local to this fixture's scope.
    """
    td = tempfile.mkdtemp(prefix="hermes-reload-skills-")
    monkeypatch.setenv("HERMES_HOME", td)
    home = Path(td)
    (home / "skills").mkdir(parents=True, exist_ok=True)

    # Import lazily (inside fixture) so the modules are already resident,
    # then redirect their captured paths at the new temp dir.
    import tools.skills_tool as _st
    import agent.skill_commands as _sc

    monkeypatch.setattr(_st, "HERMES_HOME", home, raising=False)
    monkeypatch.setattr(_st, "SKILLS_DIR", home / "skills", raising=False)
    # Reset the in-process slash-command cache so each test starts from zero.
    monkeypatch.setattr(_sc, "_skill_commands", {}, raising=False)
    monkeypatch.setattr(_sc, "_skill_payload_cache", {}, raising=False)
    monkeypatch.setattr(_sc, "_skill_payload_cache_inflight", set(), raising=False)

    yield home

    shutil.rmtree(td, ignore_errors=True)


class TestReloadSkillsHelper:
    """``agent.skill_commands.reload_skills``."""

    def test_returns_expected_keys(self, hermes_home):
        from agent.skill_commands import reload_skills

        result = reload_skills()
        assert set(result) == {"added", "removed", "unchanged", "total", "commands"}
        assert result["total"] == 0
        assert result["added"] == []
        assert result["removed"] == []

    def test_detects_newly_added_skill_with_description(self, hermes_home):
        from agent.skill_commands import reload_skills, get_skill_commands

        # Prime the cache so subsequent diff is meaningful
        get_skill_commands()

        _write_skill(hermes_home / "skills", "demo", "a demo skill")
        result = reload_skills()

        assert result["added"] == [{"name": "demo", "description": "a demo skill"}]
        assert result["removed"] == []
        assert result["total"] == 1
        assert result["commands"] == 1

    def test_detects_removed_skill_carries_description(self, hermes_home):
        from agent.skill_commands import reload_skills

        skill_dir = _write_skill(hermes_home / "skills", "demo", "soon to be gone")
        # First reload: demo present
        first = reload_skills()
        assert first["total"] == 1
        assert first["added"] == [{"name": "demo", "description": "soon to be gone"}]

        # Remove and reload — the description must survive the removal diff
        # (we cached it from the pre-rescan snapshot).
        shutil.rmtree(skill_dir)
        second = reload_skills()

        assert second["removed"] == [{"name": "demo", "description": "soon to be gone"}]
        assert second["added"] == []
        assert second["total"] == 0

    def test_description_passes_through_verbatim(self, hermes_home):
        """``description`` must be the full SKILL.md frontmatter string — no
        truncation. The system prompt renders skills as
        ``    - name: description`` without a length cap, and the reload
        note mirrors that format, so truncating here would make the diff
        render differently from the original catalog."""
        from agent.skill_commands import reload_skills, get_skill_commands

        get_skill_commands()  # prime
        long_desc = "x" * 200
        _write_skill(hermes_home / "skills", "longdesc", long_desc)

        result = reload_skills()
        assert len(result["added"]) == 1
        assert result["added"][0]["description"] == long_desc

    def test_unchanged_skills_appear_in_unchanged_list(self, hermes_home):
        from agent.skill_commands import reload_skills, get_skill_commands

        _write_skill(hermes_home / "skills", "alpha")
        # Prime cache
        get_skill_commands()

        # Call reload again with no FS changes
        result = reload_skills()
        assert "alpha" in result["unchanged"]
        assert result["added"] == []
        assert result["removed"] == []

    def test_does_not_invalidate_prompt_cache_snapshot(self, hermes_home):
        """reload_skills must NOT delete the skills prompt-cache snapshot.

        Skills are called at runtime — the system prompt doesn't need to
        mention them for the model to use them — so reloading them should
        preserve prefix caching.
        """
        from agent.prompt_builder import _skills_prompt_snapshot_path
        from agent.skill_commands import reload_skills

        snapshot = _skills_prompt_snapshot_path()
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        snapshot.write_text("{}")
        assert snapshot.exists()

        reload_skills()

        assert snapshot.exists(), (
            "prompt cache snapshot should be preserved — skills don't live "
            "in the system prompt so there's no reason to invalidate it"
        )

    def test_skill_payload_cache_hits_until_invalidated(self, hermes_home, monkeypatch):
        from agent.skill_commands import _load_skill_payload, invalidate_skill_payload_cache
        import tools.skills_tool as _st

        _write_skill(hermes_home / "skills", "demo", "cached")
        calls = {"n": 0}
        real_skill_view = _st.skill_view

        def _counting_skill_view(*args, **kwargs):
            calls["n"] += 1
            return real_skill_view(*args, **kwargs)

        monkeypatch.setattr(_st, "skill_view", _counting_skill_view)

        first = _load_skill_payload("demo")
        second = _load_skill_payload("demo")
        invalidate_skill_payload_cache("demo")
        third = _load_skill_payload("demo")

        assert first is not None
        assert second is not None
        assert third is not None
        assert calls["n"] == 2

    def test_prewarm_skill_payloads_fills_cache_in_background(self, hermes_home, monkeypatch):
        from agent import skill_commands as _sc
        from agent.skill_commands import _load_skill_payload, prewarm_skill_payloads
        import tools.skills_tool as _st

        _write_skill(hermes_home / "skills", "demo", "prewarmed")
        calls = {"n": 0}
        real_skill_view = _st.skill_view

        def _counting_skill_view(*args, **kwargs):
            calls["n"] += 1
            return real_skill_view(*args, **kwargs)

        monkeypatch.setattr(_st, "skill_view", _counting_skill_view)

        prewarm_skill_payloads(["demo", "demo"])
        deadline = time.time() + 2.0
        while time.time() < deadline:
            if calls["n"] >= 1 and _sc._skill_payload_cache:
                break
            time.sleep(0.02)

        payload = _load_skill_payload("demo")

        assert payload is not None
        assert _sc._skill_payload_cache
        assert calls["n"] == 1

    def test_load_skill_payload_waits_for_inflight_prewarm(self, hermes_home, monkeypatch):
        from agent.skill_commands import _load_skill_payload, prewarm_skill_payloads
        import tools.skills_tool as _st

        _write_skill(hermes_home / "skills", "demo", "slow-prewarm")
        calls = {"n": 0}
        real_skill_view = _st.skill_view

        def _slow_skill_view(*args, **kwargs):
            calls["n"] += 1
            time.sleep(0.08)
            return real_skill_view(*args, **kwargs)

        monkeypatch.setattr(_st, "skill_view", _slow_skill_view)

        prewarm_skill_payloads(["demo"])
        payload = _load_skill_payload("demo")

        assert payload is not None
        assert calls["n"] == 1
