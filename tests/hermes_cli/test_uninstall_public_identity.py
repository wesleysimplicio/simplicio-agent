from __future__ import annotations

from argparse import ArgumentParser

from hermes_cli.subcommands.uninstall import build_uninstall_parser


def _build_parser() -> ArgumentParser:
    parser = ArgumentParser(prog="simplicio-agent")
    subparsers = parser.add_subparsers(dest="command")
    build_uninstall_parser(subparsers, cmd_uninstall=lambda _args: None)
    return parser


def test_uninstall_help_uses_canonical_product_identity():
    parser = _build_parser()
    uninstall_parser = parser._subparsers._group_actions[0].choices["uninstall"]

    assert uninstall_parser.description == (
        "Remove Simplicio Agent from your system. Can keep configs/data for reinstall."
    )
    assert "Hermes Agent" not in uninstall_parser.description
    assert "Uninstall Simplicio Agent" in parser.format_help()
    assert "Uninstall Hermes Agent" not in parser.format_help()


def test_top_level_uninstall_usage_uses_canonical_product_identity():
    from hermes_cli import main

    assert "simplicio-agent uninstall           Uninstall Simplicio Agent" in (
        main.__doc__ or ""
    )
    assert "Uninstall Hermes Agent" not in (main.__doc__ or "")
