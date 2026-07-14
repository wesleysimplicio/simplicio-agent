"""Public identity contract for interactive CLI help."""

from copy import deepcopy

import cli as cli_module
from cli import HermesCLI
from hermes_cli.commands import COMMANDS_BY_CATEGORY


def test_help_uses_canonical_cli_without_changing_structured_commands(monkeypatch):
    """Presentation names Simplicio while the shared command model stays stable."""
    rendered = []
    structured_before = deepcopy(COMMANDS_BY_CATEGORY)

    class CaptureConsole:
        def print(self, value):
            rendered.append(str(value))

    monkeypatch.setattr(cli_module, "_cprint", lambda value: rendered.append(str(value)))
    monkeypatch.setattr(cli_module, "ChatConsole", CaptureConsole)
    monkeypatch.setattr(cli_module, "_ensure_skill_commands", lambda: {})
    monkeypatch.setattr(cli_module, "get_skill_bundles", lambda: {})

    cli = HermesCLI.__new__(HermesCLI)
    cli.config = {}
    cli.show_help()

    help_text = "\n".join(rendered)
    assert "Run `simplicio-agent` to chat" in help_text
    assert "`hermes` remains available as a legacy alias" in help_text
    assert COMMANDS_BY_CATEGORY == structured_before
