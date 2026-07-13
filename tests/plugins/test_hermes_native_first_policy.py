"""Guard the Hermes-native-first policy is codified and stable (issue #100).

The expected behavior was explicit in conversation but never pinned down as
a stable, verifiable policy: read/search/analyze -> native Hermes tools;
mutate/validate/checkpoint -> Simplicio-runtime; native fallback only as an
explicit exception for gaps the runtime doesn't cover yet.

This test covers the acceptance criteria that are mechanically checkable:
  - the default guidance mentions Hermes-native-first
  - write/patch still prefer (are routed to) the Simplicio-runtime
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


def test_policy_constant_mentions_hermes_native_first():
    assert "Hermes-native-first" in HERMES_NATIVE_FIRST_POLICY
    assert "runtime" in HERMES_NATIVE_FIRST_POLICY.lower()


def test_policy_constant_frames_native_fallback_as_explicit_exception():
    policy_lower = HERMES_NATIVE_FIRST_POLICY.lower()
    assert "fall back" in policy_lower or "fallback" in policy_lower
    assert "exception" in policy_lower
    assert "gap" in policy_lower


def test_write_and_patch_guidance_prefer_the_runtime():
    for tool_name in ("write_file", "patch"):
        guidance = _TOOL_GUIDANCE[tool_name]
        assert "simplicio edit" in guidance or "simplicio dev-cli" in guidance
        assert "read_file" in guidance or "search_files" in guidance


def test_block_message_surfaces_the_policy_and_prefers_runtime():
    result = _on_pre_tool_call(
        tool_name="write_file",
        args={"path": "/Users/wesleysimplicio/Projetos/ai/simplicio-runtime/src/main.rs", "content": "x"},
    )
    assert isinstance(result, dict)
    assert result["action"] == "block"
    assert "Hermes-native-first" in result["message"]
    assert "simplicio edit" in result["message"] or "simplicio dev-cli" in result["message"]


def test_default_soul_md_mentions_hermes_native_first():
    from hermes_cli.default_soul import DEFAULT_SOUL_MD

    assert "Hermes-native-first" in DEFAULT_SOUL_MD


def test_docker_soul_md_distinguishes_installation_from_daily_use():
    text = (REPO_ROOT / "docker" / "SOUL.md").read_text(encoding="utf-8")
    assert "Hermes-native-first" in text
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
