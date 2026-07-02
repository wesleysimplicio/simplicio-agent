"""``hermes report savings`` — wiring + dispatch (issue #16).

Two things covered:
  * the parser builder attaches ``report`` (and its ``savings`` child) and
    wires ``func`` to the injected handler, same contract as every other
    subcommand builder (see test_subcommands_followup.py);
  * ``cmd_report`` forwards to ``agent.telemetry.savings_report.main()``
    with the right argv, and produces real output end-to-end against a
    populated ledger.
"""

from __future__ import annotations

import argparse
import json

from hermes_cli.subcommands.report import build_report_parser


def _h(name):
    def handler(args):  # pragma: no cover - identity only
        return name
    handler.__name__ = f"cmd_{name}"
    return handler


def test_report_parser_dispatch():
    parser = argparse.ArgumentParser(prog="hermes")
    sub = parser.add_subparsers(dest="command")
    handler = _h("report")
    build_report_parser(sub, cmd_report=handler)
    ns = parser.parse_args(["report", "savings", "--since", "3d", "--json"])
    assert ns.command == "report"
    assert ns.func is handler
    assert ns.report_command == "savings"
    assert ns.since == "3d"
    assert ns.json is True


def test_report_savings_defaults():
    parser = argparse.ArgumentParser(prog="hermes")
    sub = parser.add_subparsers(dest="command")
    build_report_parser(sub, cmd_report=_h("report"))
    ns = parser.parse_args(["report", "savings"])
    assert ns.since == "7d"
    assert ns.json is False
    assert ns.markdown is False
    assert ns.log is None
    assert ns.out is None


def test_cmd_report_end_to_end_against_populated_ledger(tmp_path, capsys):
    from agent.telemetry.token_savings import record_token_saving
    from hermes_cli.main import cmd_report

    log_path = tmp_path / "savings.jsonl"
    record_token_saving(raw_tokens=100, compressed_tokens=60, tool="write_file", log_path=log_path)
    record_token_saving(raw_tokens=50, compressed_tokens=50, tool="search", log_path=log_path)

    args = argparse.Namespace(
        report_command="savings",
        log=str(log_path),
        since="7d",
        prices=None,
        json=True,
        markdown=False,
        out=None,
    )
    try:
        cmd_report(args)
    except SystemExit as exc:
        assert exc.code == 0

    out = capsys.readouterr().out
    report = json.loads(out)
    assert report["totals"]["raw_tokens"] == 150
    assert report["totals"]["saved_tokens"] == 40
    assert report["by_tool"]["write_file"]["saved"] == 40


def test_cmd_report_no_subcommand_prints_usage(capsys):
    from hermes_cli.main import cmd_report

    cmd_report(argparse.Namespace(report_command=None))
    out = capsys.readouterr().out
    assert "hermes report savings" in out
