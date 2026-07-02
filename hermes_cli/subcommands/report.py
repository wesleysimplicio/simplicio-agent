"""``hermes report`` subcommand group.

Wires the previously-dormant token-savings telemetry stack
(``agent.telemetry.token_savings`` / ``savings_report``) to a real CLI
entry point (issue #16). Currently one report: ``hermes report savings``.
"""

from __future__ import annotations

from typing import Callable


def build_report_parser(subparsers, *, cmd_report: Callable) -> None:
    """Attach the ``report`` subcommand (and its ``savings`` child) to ``subparsers``."""
    report_parser = subparsers.add_parser(
        "report",
        help="Reports built from Hermes telemetry",
        description="Reports built from Hermes telemetry (token savings and similar).",
    )
    report_subparsers = report_parser.add_subparsers(dest="report_command")

    savings_parser = report_subparsers.add_parser(
        "savings",
        help="Token savings report (TOON conversions and other savings events)",
        description=(
            "Aggregate the token-savings ledger "
            "(~/.hermes/telemetry/token_savings.jsonl by default) into a report."
        ),
    )
    savings_parser.add_argument(
        "--log", default=None,
        help="Path to the JSONL savings log (default: ~/.hermes/telemetry/token_savings.jsonl).",
    )
    savings_parser.add_argument(
        "--since", default="7d",
        help="Time window for the report, e.g. 7d, 24h, 4w (default: 7d).",
    )
    savings_parser.add_argument(
        "--prices", default=None,
        help="Optional JSON file overriding USD/1M-token prices per adapter.",
    )
    savings_parser.add_argument("--json", action="store_true", help="Emit JSON.")
    savings_parser.add_argument(
        "--markdown", action="store_true", help="Emit Markdown (Slack/email/GH-friendly).",
    )
    savings_parser.add_argument(
        "--out", default=None, help="Write to file instead of stdout.",
    )

    report_parser.set_defaults(func=cmd_report)
