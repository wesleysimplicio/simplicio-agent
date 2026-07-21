"""Guard the Simplicio-runtime-first policy is codified and stable.

The central native-tool dispatcher attempts Simplicio Runtime first. Native
fallback remains an explicit exception for gaps the runtime doesn't cover yet.

This test covers the acceptance criteria that are mechanically checkable:
  - the default guidance mentions Simplicio-runtime-first
  - write/patch guidance names the central Runtime adapter
  - the native fallback is framed as an explicit exception, not a silent
    substitute
  - user-facing setup text distinguishes "installation" from "daily use"
"""

from __future__ import annotations

from pathlib import Path

from plugins.simplicio import (
    HERMES_NATIVE_FIRST_POLICY,
    _TOOL_GUIDANCE,
    _on_pre_tool_call,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_policy_constant_mentions_runtime_first():
    assert "Simplicio-runtime-first" in HERMES_NATIVE_FIRST_POLICY
    assert "runtime" in HERMES_NATIVE_FIRST_POLICY.lower()


def test_policy_constant_frames_native_fallback_as_explicit_exception():
    policy_lower = HERMES_NATIVE_FIRST_POLICY.lower()
    assert "fall back" in policy_lower or "fallback" in policy_lower
    assert "exception" in policy_lower
    assert "gap" in policy_lower


def test_write_and_patch_guidance_prefer_the_runtime():
    for tool_name in ("write_file", "patch"):
        guidance = _TOOL_GUIDANCE[tool_name]
        assert "simplicio edit" in guidance
        assert "Runtime adapter" in guidance


def test_pre_tool_hook_does_not_block_before_runtime_adapter():
    result = _on_pre_tool_call(
        tool_name="write_file",
        args={"path": "/Users/wesleysimplicio/Projetos/ai/simplicio-runtime/src/main.rs", "content": "x"},
    )
    assert result is None


def test_default_soul_md_mentions_runtime_first():
    from hermes_cli.default_soul import DEFAULT_SOUL_MD

    assert "Simplicio-runtime-first" in DEFAULT_SOUL_MD


def test_docker_soul_md_distinguishes_installation_from_daily_use():
    text = (REPO_ROOT / "docker" / "SOUL.md").read_text(encoding="utf-8")
    assert "Simplicio-runtime-first" in text
    assert "Instalação" in text or "instalação" in text
    assert "uso diário" in text.lower()
    # The daily-use policy line itself, not just a heading.
    assert "fallback" in text.lower()
    assert "exce" in text.lower()  # "exceção" / "excecao"


def test_setup_script_distinguishes_installation_from_daily_use():
    text = (REPO_ROOT / "setup-hermes.sh").read_text(encoding="utf-8")
    assert "INSTALL" in text
    assert "DAILY USE" in text
    assert "native fallback" in text.lower()
