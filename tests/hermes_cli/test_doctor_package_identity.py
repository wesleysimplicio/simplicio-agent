from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path

import hermes_cli.doctor as doctor


def _write_project(root: Path, *, version: str = "0.25.0") -> None:
    (root / "pyproject.toml").write_text(
        '[project]\nname = "simplicio-agent"\nversion = "' + version + '"\n',
        encoding="utf-8",
    )


def _write_manifest(root: Path, *, package: str, name: str, identifier: str) -> None:
    manifest_dir = root / "acp_registry"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    (manifest_dir / "agent.json").write_text(
        json.dumps(
            {
                "id": identifier,
                "name": name,
                "version": "0.25.0",
                "description": "test",
                "repository": "https://github.com/wesleysimplicio/simplicio-agent",
                "website": "https://hermes-agent.nousresearch.com/docs/user-guide/features/acp",
                "authors": ["Nous Research"],
                "license": "MIT",
                "distribution": {
                    "uvx": {
                        "package": package,
                        "args": ["hermes-acp"],
                    }
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _run_check(project_root: Path):
    issues: list[str] = []
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        doctor._check_package_identity(issues)
    return buf.getvalue(), issues


def test_package_identity_check_passes_for_canonical_manifest(tmp_path, monkeypatch):
    project_root = tmp_path / "project"
    project_root.mkdir()
    _write_project(project_root)
    _write_manifest(
        project_root,
        package="simplicio-agent[acp]==0.25.0",
        name="Simplicio Agent",
        identifier="simplicio-agent",
    )
    monkeypatch.setattr(doctor, "PROJECT_ROOT", project_root)

    out, issues = _run_check(project_root)

    assert "Package Identity" in out
    assert "ACP registry manifest" in out
    assert issues == []


def test_package_identity_check_flags_legacy_acp_manifest(tmp_path, monkeypatch):
    project_root = tmp_path / "project"
    project_root.mkdir()
    _write_project(project_root)
    _write_manifest(
        project_root,
        package="hermes-agent[acp]==0.25.0",
        name="Hermes Agent",
        identifier="hermes-agent",
    )
    monkeypatch.setattr(doctor, "PROJECT_ROOT", project_root)

    out, issues = _run_check(project_root)

    assert "ACP registry manifest identity drift" in out
    assert "simplicio-agent[acp]==0.25.0" in out
    assert any("sync acp_registry/agent.json" in issue for issue in issues)
