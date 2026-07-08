"""``simplicio-agent daemon`` subcommand parser.

Attaches the warm-daemon lifecycle commands (``start``/``stop``/``status``/
``invalidate``) to ``subparsers``, mirroring ``hermes_cli/subcommands/cron.py``:
same shape, handler injected to avoid importing ``main`` (cycle avoidance).

The actual daemon implementation (socket server, real preloaders) lives in
``hermes_cli/daemon.py``.
"""

from __future__ import annotations

from typing import Callable

from hermes_cli.daemon import PRELOADERS, PROFILES


def build_daemon_parser(subparsers, *, cmd_daemon: Callable) -> None:
    """Attach the ``daemon`` subcommand (and its sub-actions) to ``subparsers``."""
    daemon_parser = subparsers.add_parser(
        "daemon",
        help="Warm daemon management",
        description="Manage the Hermes warm daemon (preloaded tool/skill/provider/MCP/session caches)",
    )
    daemon_subparsers = daemon_parser.add_subparsers(dest="daemon_command")

    # daemon start
    #
    # NOTE: the warm-cache selector is intentionally named ``--warm-profile``,
    # not ``--profile``. ``hermes_cli/main.py``'s ``_apply_profile_override()``
    # pre-parses ``--profile``/``-p`` out of sys.argv *before* argparse ever
    # runs (it selects the Hermes environment/config profile, e.g.
    # ``simplicio-agent -p coder chat``). Reusing that flag name here would silently
    # get intercepted by that global pre-parser instead of reaching this
    # subcommand.
    daemon_start = daemon_subparsers.add_parser(
        "start", help="Start the warm daemon (foreground)"
    )
    daemon_start.add_argument(
        "--warm-profile", dest="profile", choices=PROFILES, default="desktop",
        help="Warm-cache preload set to use (desktop: all caches, car: reduced set)",
    )
    daemon_start.add_argument("--socket", default=None)

    # daemon stop
    daemon_stop = daemon_subparsers.add_parser("stop", help="Stop the warm daemon")
    daemon_stop.add_argument("--socket", default=None)

    # daemon status
    daemon_status = daemon_subparsers.add_parser("status", help="Show daemon status")
    daemon_status.add_argument("--socket", default=None)

    # daemon invalidate
    daemon_invalidate = daemon_subparsers.add_parser(
        "invalidate", help="Invalidate a warm cache"
    )
    daemon_invalidate.add_argument("cache", choices=tuple(PRELOADERS))
    daemon_invalidate.add_argument("--socket", default=None)

    daemon_parser.set_defaults(func=cmd_daemon)
