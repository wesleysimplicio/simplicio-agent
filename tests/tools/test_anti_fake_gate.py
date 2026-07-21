from __future__ import annotations

from pathlib import Path

from tools.anti_fake_gate import scan_paths


def test_anti_fake_gate_rejects_silent_handlers_and_synthetic_success(tmp_path: Path):
    source = tmp_path / "handlers.py"
    source.write_text(
        "def silent_handler():\n    pass\n\n"
        "def fake_execute():\n    return {'ok': True}\n"
    )

    violations = scan_paths((source,))

    assert {violation.kind for violation in violations} == {
        "silent-pass",
        "synthetic-success",
    }


def test_anti_fake_gate_has_no_current_production_violations():
    violations = scan_paths((Path("agent"), Path("tools")))
    assert violations == []
