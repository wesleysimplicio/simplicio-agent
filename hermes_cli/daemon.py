"""Hermes warm daemon — keeps expensive runtime state hot for desktop/car profiles.

Goal: avoid paying full startup/discovery cost on every interaction. The daemon
preloads tool registry, skill index, provider metadata, MCP/config fingerprints
and recent session summaries, then exposes a tiny request loop over a UNIX
socket. CLI clients connect, send a JSON request, get a JSON response.

Each preloader is backed by this repo's real systems (toolsets, skills/ tree,
agent/models_dev.py provider map, hermes_cli/mcp_catalog.py, hermes_state.py
SessionDB) and degrades gracefully — never raises — if the underlying system
isn't available in a given environment.

Subcommands:
    simplicio-agent daemon start [--profile desktop|car] [--socket PATH] [--idle-ttl-s N]
    simplicio-agent daemon stop  [--socket PATH]
    simplicio-agent daemon status [--socket PATH]

Fallback: when the daemon socket is missing or unresponsive, callers MUST
re-execute the cold path. Never block UX on a warm daemon.

Auto-start (issue #110): interactive CLI/TUI entry points may call
``maybe_autostart()`` to spawn this daemon in the background on first use so
later invocations hit the warm path instead of paying cold discovery every
time. Auto-start is skipped entirely for one-shot/non-interactive invocations
(``-q``/``--query``, non-TTY stdin/stdout, CI) — those callers never import
or call ``maybe_autostart()`` in the first place (see
``hermes_cli/main.py::_should_autostart_daemon``). Set
``SIMPLICIO_AGENT_NO_DAEMON=1`` to opt out unconditionally (no background
process is ever spawned, regardless of interactivity).

Idle shutdown: a spawned/attended daemon tracks time since its last accepted
connection and exits on its own once ``SIMPLICIO_AGENT_DAEMON_IDLE_TTL_S``
(default: 1800s / 30min) elapses with no activity, so auto-start never leaks
a process that lives forever. Override per-run with ``daemon start
--idle-ttl-s N``.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

from agent.host import AgentHost, HostBackpressure, HostShutdown

try:
    from hermes_constants import get_hermes_home
except ImportError:  # pragma: no cover - only during isolated/partial checkouts
    get_hermes_home = None  # type: ignore[assignment]

PROFILES = ("desktop", "car")


def _hermes_home() -> Path:
    if get_hermes_home is not None:
        try:
            return get_hermes_home()
        except Exception:  # pragma: no cover - defensive, never block on this
            pass
    return Path.home() / ".hermes"


DEFAULT_SOCKET = _hermes_home() / "daemon.sock"
DEFAULT_PIDFILE = _hermes_home() / "daemon.pid"


def _socket_path(arg: str | None) -> Path:
    return Path(arg) if arg else DEFAULT_SOCKET


def _pid_path(sock: Path) -> Path:
    return sock.with_suffix(".pid")


def _ensure_dir(p: Path) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Auto-start / idle-TTL (issue #110)
# ---------------------------------------------------------------------------

DEFAULT_IDLE_TTL_S = 1800.0  # 30 minutes


def _no_daemon_opt_out() -> bool:
    """Read the ``SIMPLICIO_AGENT_NO_DAEMON`` kill-switch.

    Mirrors the other ``SIMPLICIO_*_NO_*`` kill-switches used across the
    Simplicio ecosystem (e.g. ``SIMPLICIO_MAPPER_NO_RUNTIME_PRECEDENT``):
    unset/empty/"0"/"false"/"no" means "not opted out"; anything else opts out.
    """
    raw = os.environ.get("SIMPLICIO_AGENT_NO_DAEMON", "").strip().lower()
    return raw not in ("", "0", "false", "no")


def _idle_ttl_s(override: float | None = None) -> float:
    if override is not None:
        return max(1.0, float(override))
    raw = os.environ.get("SIMPLICIO_AGENT_DAEMON_IDLE_TTL_S")
    if not raw:
        return DEFAULT_IDLE_TTL_S
    try:
        return max(1.0, float(raw))
    except ValueError:
        return DEFAULT_IDLE_TTL_S


def is_daemon_running(sock_path: Path | None = None, timeout: float = 1.0) -> bool:
    """True only when a live daemon answers a real ``ping`` over the socket."""
    resp = _client_request(sock_path or DEFAULT_SOCKET, {"op": "ping"}, timeout=timeout)
    return bool(resp.get("ok")) and resp.get("pong") is True


def maybe_autostart(sock_path: Path | None = None, profile: str = "desktop") -> bool:
    """Best-effort background auto-start for an interactive CLI/TUI invocation.

    Never raises and never blocks the caller — any failure here just means
    the caller falls back to the existing cold path, per this module's
    fallback contract. Returns True only when a new background daemon
    process was actually spawned by this call.

    Callers are responsible for deciding *whether* this is an interactive,
    auto-start-eligible invocation (see
    ``hermes_cli/main.py::_should_autostart_daemon``); this function only
    handles the opt-out kill-switch and the actual spawn/dedupe.
    """
    if _no_daemon_opt_out():
        return False
    sock_path = sock_path or DEFAULT_SOCKET
    try:
        if is_daemon_running(sock_path, timeout=0.3):
            return False  # already warm — nothing to do
        _ensure_dir(sock_path)
        popen_kwargs: dict[str, Any] = {
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "stdin": subprocess.DEVNULL,
            "cwd": str(Path(__file__).resolve().parent.parent),
        }
        if sys.platform == "win32":
            popen_kwargs["creationflags"] = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
                subprocess, "CREATE_NEW_PROCESS_GROUP", 0
            )
        else:
            popen_kwargs["start_new_session"] = True
        subprocess.Popen(
            [
                sys.executable, "-m", "hermes_cli.daemon", "start",
                "--warm-profile", profile, "--socket", str(sock_path),
            ],
            **popen_kwargs,
        )
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Warm caches (lazy, real-system-backed)
# ---------------------------------------------------------------------------


def _preload_tool_registry() -> dict[str, Any]:
    """Inspect the real toolset catalog (``toolsets.py``) for live counts."""
    try:
        import toolsets

        names = toolsets.get_toolset_names()
        return {"ok": True, "module": "toolsets", "toolset_count": len(names), "toolsets": names}
    except Exception as exc:  # pragma: no cover - environment-dependent
        return {"ok": False, "error": repr(exc)}


def _preload_skill_index() -> dict[str, Any]:
    """Count real installed skills under ``skills/`` (recursive SKILL.md scan)."""
    skills_dir = Path(__file__).resolve().parent.parent / "skills"
    if not skills_dir.exists():
        return {"ok": False, "error": "skills/ missing"}
    try:
        manifests = sorted(skills_dir.glob("**/SKILL.md"))
        names = [m.parent.name for m in manifests]
        return {"ok": True, "count": len(manifests), "skills": names}
    except Exception as exc:  # pragma: no cover - environment-dependent
        return {"ok": False, "error": repr(exc)}


def _preload_provider_metadata() -> dict[str, Any]:
    """Return the real provider list from ``agent/models_dev.py``."""
    try:
        from agent.models_dev import PROVIDER_TO_MODELS_DEV

        providers = sorted(PROVIDER_TO_MODELS_DEV.keys())
        return {"ok": True, "providers": providers, "count": len(providers)}
    except Exception as exc:  # pragma: no cover - environment-dependent
        return {"ok": False, "error": repr(exc)}


def _preload_mcp_fingerprints() -> dict[str, Any]:
    """Return real configured MCP server names from ``hermes_cli/mcp_catalog.py``."""
    try:
        from hermes_cli.mcp_catalog import installed_servers

        servers = installed_servers()
        fingerprints = {
            name: {
                "enabled": bool((cfg or {}).get("enabled", True)) if isinstance(cfg, dict) else True,
            }
            for name, cfg in servers.items()
        }
        return {"ok": True, "fingerprints": fingerprints, "count": len(fingerprints)}
    except Exception as exc:  # pragma: no cover - environment-dependent
        return {"ok": False, "error": repr(exc)}


def _recent_session_summaries(limit: int = 5) -> list[dict[str, Any]]:
    """Read-only helper: fetch the N most-recent session summaries.

    Lives in ``daemon.py`` (not ``hermes_state.py``) so this module stays a
    pure consumer of ``SessionDB`` — it only imports and calls the existing
    ``list_sessions_rich`` read API, never mutates session state.
    """
    from hermes_state import SessionDB

    db = SessionDB()
    rows = db.list_sessions_rich(limit=limit, order_by_last_active=True)
    return [
        {
            "id": row.get("id"),
            "source": row.get("source"),
            "title": row.get("title"),
            "preview": row.get("preview"),
            "last_active": row.get("last_active"),
            "message_count": row.get("message_count"),
        }
        for row in rows
    ]


def _preload_session_summaries() -> dict[str, Any]:
    """Return real recent session summaries from ``hermes_state.SessionDB``."""
    try:
        summaries = _recent_session_summaries(limit=5)
        return {"ok": True, "summaries": summaries, "count": len(summaries)}
    except Exception as exc:  # pragma: no cover - environment-dependent
        return {"ok": False, "error": repr(exc)}


PRELOADERS: dict[str, Callable[[], dict[str, Any]]] = {
    "tool_registry": _preload_tool_registry,
    "skill_index": _preload_skill_index,
    "provider_metadata": _preload_provider_metadata,
    "mcp_fingerprints": _preload_mcp_fingerprints,
    "session_summaries": _preload_session_summaries,
}


PROFILE_PRELOADS: dict[str, tuple[str, ...]] = {
    "desktop": tuple(PRELOADERS),
    "car": ("tool_registry", "skill_index", "provider_metadata"),
}


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------


def _serve(sock_path: Path, profile: str, idle_ttl_s: float | None = None) -> int:
    if profile not in PROFILES:
        print(f"unknown profile: {profile}", file=sys.stderr)
        return 2

    _ensure_dir(sock_path)
    if sock_path.exists():
        sock_path.unlink()

    pid_path = _pid_path(sock_path)
    pid_path.write_text(str(os.getpid()))

    caches: dict[str, dict[str, Any]] = {}
    for name in PROFILE_PRELOADS[profile]:
        caches[name] = PRELOADERS[name]()

    # The warm daemon is a real AgentHost surface.  The host owns identity,
    # leases, and turn ordering while AIAgent remains the execution engine.
    def make_agent(identity: Any) -> Any:
        from run_agent import AIAgent

        return AIAgent(session_id=identity.session_id)

    host = AgentHost(make_agent, max_sessions=32, max_workers=4, max_pending=64)
    started = time.time()
    idle_ttl = _idle_ttl_s(idle_ttl_s)
    # Poll interval for the idle-TTL check: never longer than the TTL itself,
    # so a very short TTL (e.g. in tests) is still observed promptly.
    poll_s = min(1.0, idle_ttl / 2) if idle_ttl < 2 else 1.0
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(str(sock_path))
    srv.listen(8)
    os.chmod(sock_path, 0o600)
    srv.settimeout(poll_s)

    print(
        f"simplicio-agent daemon ready profile={profile} socket={sock_path} "
        f"idle_ttl_s={idle_ttl}",
        flush=True,
    )

    last_activity = time.time()
    try:
        while True:
            try:
                conn, _ = srv.accept()
            except socket.timeout:
                if time.time() - last_activity >= idle_ttl:
                    print(
                        f"simplicio-agent daemon idle for {idle_ttl}s — shutting down",
                        flush=True,
                    )
                    break
                continue

            last_activity = time.time()
            with conn:
                try:
                    raw = conn.recv(8192).decode("utf-8", errors="replace")
                    req = json.loads(raw or "{}")
                except json.JSONDecodeError as exc:
                    conn.sendall(json.dumps({"ok": False, "error": str(exc)}).encode())
                    continue

                op = req.get("op", "status")
                if op == "status":
                    resp = {
                        "ok": True,
                        "profile": profile,
                        "uptime_s": round(time.time() - started, 2),
                        "caches": list(caches),
                        "idle_ttl_s": idle_ttl,
                        "idle_s": round(time.time() - last_activity, 2),
                    }
                elif op == "ping":
                    resp = {"ok": True, "pong": True}
                elif op == "invalidate":
                    target = req.get("cache")
                    if target in PRELOADERS:
                        caches[target] = PRELOADERS[target]()
                        resp = {"ok": True, "invalidated": target}
                    else:
                        resp = {"ok": False, "error": f"unknown cache: {target}"}
                elif op == "host.status":
                    resp = {"ok": True, "host": host.status()}
                elif op == "turn.start":
                    try:
                        future = host.submit(
                            str(req.get("profile", profile)),
                            str(req["session_id"]),
                            str(req["message"]),
                            idempotency_key=req.get("idempotency_key"),
                            incarnation=str(req.get("incarnation", "default")),
                            revision=int(req.get("revision", 0)),
                        )
                        result = future.result(timeout=float(req.get("timeout", 300)))
                        resp = {"ok": True, "result": result}
                    except (KeyError, ValueError) as exc:
                        resp = {"ok": False, "error": str(exc)}
                    except HostBackpressure as exc:
                        resp = {"ok": False, "error": str(exc), "retryable": True}
                    except HostShutdown as exc:
                        resp = {"ok": False, "error": str(exc), "retryable": False}
                    except Exception as exc:
                        # The daemon returns a stable envelope; raw provider
                        # details remain in the existing AIAgent logs.
                        resp = {"ok": False, "error": type(exc).__name__}
                elif op == "shutdown":
                    conn.sendall(json.dumps({"ok": True, "bye": True}).encode())
                    break
                else:
                    resp = {"ok": False, "error": f"unknown op: {op}"}

                conn.sendall(json.dumps(resp).encode())
    finally:
        host.shutdown()
        srv.close()
        if sock_path.exists():
            sock_path.unlink()
        if pid_path.exists():
            pid_path.unlink()
    return 0


def _client_request(sock_path: Path, payload: dict[str, Any], timeout: float = 2.0) -> dict[str, Any]:
    if not sock_path.exists():
        return {"ok": False, "error": "daemon not running", "fallback": "cold"}
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as c:
            c.settimeout(timeout)
            c.connect(str(sock_path))
            c.sendall(json.dumps(payload).encode())
            data = c.recv(65536)
            return json.loads(data.decode("utf-8", errors="replace") or "{}")
    except (OSError, json.JSONDecodeError) as exc:
        return {"ok": False, "error": repr(exc), "fallback": "cold"}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="hermes-daemon", description="Hermes warm daemon")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("start", help="Start the warm daemon (foreground)")
    s.add_argument("--warm-profile", dest="profile", choices=PROFILES, default="desktop")
    s.add_argument("--socket", default=None)
    s.add_argument(
        "--idle-ttl-s", dest="idle_ttl_s", type=float, default=None,
        help=(
            "Idle TTL in seconds before auto-shutdown "
            "(default: $SIMPLICIO_AGENT_DAEMON_IDLE_TTL_S or 1800)"
        ),
    )

    st = sub.add_parser("stop", help="Stop the warm daemon")
    st.add_argument("--socket", default=None)

    ss = sub.add_parser("status", help="Show daemon status")
    ss.add_argument("--socket", default=None)

    inv = sub.add_parser("invalidate", help="Invalidate a warm cache")
    inv.add_argument("cache", choices=tuple(PRELOADERS))
    inv.add_argument("--socket", default=None)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    sock = _socket_path(args.socket)

    if args.cmd == "start":
        return _serve(sock, args.profile, idle_ttl_s=args.idle_ttl_s)
    if args.cmd == "stop":
        resp = _client_request(sock, {"op": "shutdown"})
        print(json.dumps(resp))
        return 0 if resp.get("ok") else 1
    if args.cmd == "status":
        resp = _client_request(sock, {"op": "status"})
        print(json.dumps(resp, indent=2))
        return 0 if resp.get("ok") else 1
    if args.cmd == "invalidate":
        resp = _client_request(sock, {"op": "invalidate", "cache": args.cache})
        print(json.dumps(resp))
        return 0 if resp.get("ok") else 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
