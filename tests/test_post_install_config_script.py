from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "post-install-config.sh"


def _run(tmp_path: Path, profile: str) -> subprocess.CompletedProcess[str]:
    home = tmp_path / "home"
    home.mkdir()
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["HERMES_HOME"] = str(home / ".simplicio_agent")
    env["SIMPLICIO_INSTALL_PROFILE"] = profile
    return subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_post_install_creates_normal_profile_config(tmp_path: Path) -> None:
    result = _run(tmp_path, "normal")
    assert result.returncode == 0, result.stderr
    config_path = tmp_path / "home" / ".simplicio_agent" / "config.yaml"
    assert config_path.exists()
    content = config_path.read_text(encoding="utf-8")
    assert "max_concurrent_children: 32" in content
    assert "max_spawn_depth: 3" in content
    assert "orchestrator_enabled: true" in content
    assert "max_turns: 200" in content
    assert "install_speed_profile: normal" in content
    assert "Perfil detectado: normal" in result.stdout


def test_post_install_honors_full_profile_and_repo_relative_onboarding(tmp_path: Path) -> None:
    result = _run(tmp_path, "full")
    assert result.returncode == 0, result.stderr
    config_path = tmp_path / "home" / ".simplicio_agent" / "config.yaml"
    content = config_path.read_text(encoding="utf-8")
    assert "max_concurrent_children: 64" in content
    assert "install_speed_profile: full" in content

    onboarding = (
        tmp_path
        / "home"
        / ".simplicio_agent"
        / "onboarding"
        / "SIMPLICIO-AGENT-GUIDE.md"
    )
    assert onboarding.exists()
