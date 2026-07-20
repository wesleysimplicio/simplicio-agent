from __future__ import annotations

import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "tools" / "simplicio_agent_launcher.sh"


def _fake_bundle(tmp_path: Path) -> tuple[Path, Path]:
    home = tmp_path / "agent-home"
    python = home / "current" / "venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text(
        "#!/bin/sh\n"
        "printf 'HERMES_HOME=%s\\n' \"$HERMES_HOME\"\n"
        "printf 'SIMPLICIO_AGENT_HOME=%s\\n' \"$SIMPLICIO_AGENT_HOME\"\n"
        "printf '%s\\n' \"$@\"\n",
        encoding="utf-8",
    )
    python.chmod(0o755)
    return home, python


def _run_launcher(home: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["SIMPLICIO_AGENT_HOME"] = str(home)
    env["HERMES_HOME"] = str(home / "wrong-inherited-agent")
    env["SIMPLICIO_AGENT_USE_LAUNCHD"] = "0"
    return subprocess.run(
        [str(LAUNCHER), *args],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_no_arguments_start_gateway_without_entering_chat(tmp_path: Path) -> None:
    home, _ = _fake_bundle(tmp_path)

    result = _run_launcher(home)

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        f"HERMES_HOME={home}",
        f"SIMPLICIO_AGENT_HOME={home}",
        "-m",
        "hermes_cli.main",
        "gateway",
        "start",
    ]


def test_explicit_chat_remains_available(tmp_path: Path) -> None:
    home, _ = _fake_bundle(tmp_path)

    result = _run_launcher(home, "chat", "-q", "hello")

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        f"HERMES_HOME={home}",
        f"SIMPLICIO_AGENT_HOME={home}",
        "-m",
        "hermes_cli.main",
        "chat",
        "-q",
        "hello",
    ]
