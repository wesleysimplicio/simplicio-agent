"""Public identity contract for interactive CLI help."""

from pathlib import Path


def test_help_uses_canonical_cli_without_changing_structured_commands():
    """The user-facing help source names Simplicio without importing optional UI deps."""
    source = (Path(__file__).resolve().parents[2] / "cli.py").read_text(
        encoding="utf-8"
    )

    assert "Run `simplicio-agent` to chat" in source
    assert "`hermes` remains available as a legacy alias" in source
