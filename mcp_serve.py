"""
Simplicio Agent MCP Server — the public gateway for external LLM clients.

Starts a stdio MCP server that lets Cursor, VS Code, Gemini, Antigravity, Claude,
Codex, and other MCP clients ask the autonomous Agent to act, recall Runtime
capabilities lazily, and interact with connected messaging channels.

Matches OpenClaw's 9-tool MCP channel bridge surface:
  conversations_list, conversation_get, messages_read, attachments_fetch,
  events_poll, events_wait, messages_send, permissions_list_open,
  permissions_respond

Plus: channels_list (Simplicio Agent-specific extra)

Usage:
    simplicio-agent mcp serve
    simplicio-agent mcp serve --verbose

MCP client config (e.g. claude_desktop_config.json):
    {
        "mcpServers": {
            "Simplicio Agent": {
                "command": "simplicio-agent",
                "args": ["mcp", "serve"]
            }
        }
    }
"""

from __future__ import annotations

import json

# Hot-path JSON: every MCP tool result goes through dumps below. orjson-backed
# with graceful stdlib fallback (agent/_fastjson.py).
from agent._fastjson import dumps as _fast_dumps, loads as _fast_loads
from agent.mcp_agent_gateway import invoke_agent, rank_capabilities
from simplicio_agent.public_contract import MCP_SERVER_NAME
import logging
import os
import re
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("simplicio.mcp_serve")

# ---------------------------------------------------------------------------
# Lazy MCP SDK import
# ---------------------------------------------------------------------------

_MCP_SERVER_AVAILABLE = False
try:
    from mcp.server.fastmcp import FastMCP

    _MCP_SERVER_AVAILABLE = True
except ImportError:
    FastMCP = None  # type: ignore[assignment,misc]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_hermes_home() -> Path:
    """Return the Hermes/Simplicio home directory.

    Delegates to ``hermes_constants.get_hermes_home()`` — the single source
    of truth for HOME resolution (override, ``SIMPLICIO_AGENT_HOME`` /
    ``HERMES_HOME`` aliasing, platform default, and migration state). Never
    duplicates that default locally: a hardcoded ``Path.home() / ".hermes"``
    here would silently drift once the accessor's default/migration logic
    changes (issue #117). ``ImportError`` only fires if ``hermes_constants``
    genuinely isn't on ``sys.path`` (e.g. this module run standalone outside
    the package); in that narrow case we still read the same two env vars in
    the same precedence order, with the current platform default as the
    last resort, but do not carry any migration/profile logic.
    """
    try:
        from hermes_constants import get_hermes_home
        return get_hermes_home()
    except ImportError:
        val = (os.environ.get("SIMPLICIO_AGENT_HOME") or os.environ.get("HERMES_HOME") or "").strip()
        return Path(val) if val else Path.home() / ".hermes"


def _get_sessions_dir() -> Path:
    """Return the sessions directory using HERMES_HOME."""
    return _resolve_hermes_home() / "sessions"


def _get_session_db():
    """Get a SessionDB instance for reading message transcripts."""
    try:
        from hermes_state import SessionDB
        return SessionDB()
    except Exception as e:
        logger.debug("SessionDB unavailable: %s", e)
        return None


def _load_sessions_index() -> dict:
    """Load the gateway sessions.json index directly.

    Returns a dict of session_key -> entry_dict with platform routing info.
    This avoids importing the full SessionStore which needs GatewayConfig.
    """
    sessions_file = _get_sessions_dir() / "sessions.json"
    if not sessions_file.exists():
        return {}
    try:
        with open(sessions_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Drop documentation/metadata sentinels (keys starting with "_", e.g.
        # the "_README" note the gateway writes into the index). They are not
        # session entries and would break consumers that treat every value as
        # an entry dict.
        if isinstance(data, dict):
            return {k: v for k, v in data.items() if not str(k).startswith("_")}
        return {}
    except Exception as e:
        logger.debug("Failed to load sessions.json: %s", e)
        return {}


def _load_channel_directory() -> dict:
    """Load the cached channel directory for available targets."""
    directory_file = _resolve_hermes_home() / "channel_directory.json"

    if not directory_file.exists():
        return {}
    try:
        with open(directory_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.debug("Failed to load channel_directory.json: %s", e)
        return {}


def _coerce_int(
    value,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    """Coerce value to int with fallback and clamping.

    Used at MCP tool boundaries to handle invalid types from external clients.
    Returns default if value cannot be converted to int.
    """
    try:
        coerced = int(value)
    except (TypeError, ValueError):
        coerced = default
    return max(minimum, min(coerced, maximum))


def _extract_message_content(msg: dict) -> str:
    """Extract text content from a message, handling multi-part content."""
    content = msg.get("content", "")
    if isinstance(content, list):
        text_parts = [
            p.get("text", "") for p in content
            if isinstance(p, dict) and p.get("type") == "text"
        ]
        return "\n".join(text_parts)
    return str(content) if content else ""


def _extract_attachments(msg: dict) -> List[dict]:
    """Extract non-text attachments from a message.

    Finds: multi-part image/file content blocks, MEDIA: tags in text,
    image URLs, and file references.
    """
    attachments = []
    content = msg.get("content", "")

    # Multi-part content blocks (image_url, file, etc.)
    if isinstance(content, list):
        for part in content:
            if not isinstance(part, dict):
                continue
            ptype = part.get("type", "")
            if ptype == "image_url":
                url = part.get("image_url", {}).get("url", "") if isinstance(part.get("image_url"), dict) else ""
                if url:
                    attachments.append({"type": "image", "url": url})
            elif ptype == "image":
                url = part.get("url", part.get("source", {}).get("url", ""))
                if url:
                    attachments.append({"type": "image", "url": url})
            elif ptype not in {"text",}:
                # Unknown non-text content type
                attachments.append({"type": ptype, "data": part})

    # MEDIA: tags in text content
    text = _extract_message_content(msg)
    if text:
        media_pattern = re.compile(r'MEDIA:\s*(\S+)')
        for match in media_pattern.finditer(text):
            path = match.group(1)
            attachments.append({"type": "media", "path": path})

    return attachments


# ---------------------------------------------------------------------------
# Event Bridge — polls SessionDB for new messages, maintains event queue
# ---------------------------------------------------------------------------

QUEUE_LIMIT = 1000
POLL_INTERVAL = 0.2  # seconds between DB polls (200ms)


@dataclass
class QueueEvent:
    """An event in the bridge's in-memory queue."""
    cursor: int
    type: str  # "message", "approval_requested", "approval_resolved"
    session_key: str = ""
    data: dict = field(default_factory=dict)


class EventBridge:
    """Background poller that watches SessionDB for new messages and
    maintains an in-memory event queue with waiter support.

    This is the Hermes equivalent of OpenClaw's WebSocket gateway bridge.
    Instead of WebSocket events, we poll the SQLite database for changes.
    """

    def __init__(self):
        self._queue: List[QueueEvent] = []
        self._cursor = 0
        self._lock = threading.Lock()
        self._new_event = threading.Event()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._last_poll_timestamps: Dict[str, float] = {}  # session_key -> unix timestamp
        # In-memory approval tracking (populated from events)
        self._pending_approvals: Dict[str, dict] = {}
        # mtime cache — skip expensive work when files haven't changed
        self._sessions_json_mtime: float = 0.0
        self._state_db_mtime: float = 0.0
        self._cached_sessions_index: dict = {}

    def start(self):
        """Start the background polling thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()
        logger.debug("EventBridge started")

    def stop(self):
        """Stop the background polling thread."""
        self._running = False
        self._new_event.set()  # Wake any waiters
        if self._thread:
            self._thread.join(timeout=5)
        logger.debug("EventBridge stopped")

    def poll_events(
        self,
        after_cursor: int = 0,
        session_key: Optional[str] = None,
        limit: int = 20,
    ) -> dict:
        """Return events since after_cursor, optionally filtered by session_key."""
        with self._lock:
            events = [
                e for e in self._queue
                if e.cursor > after_cursor
                and (not session_key or e.session_key == session_key)
            ][:limit]

        next_cursor = events[-1].cursor if events else after_cursor
        return {
            "events": [
                {"cursor": e.cursor, "type": e.type,
                 "session_key": e.session_key, **e.data}
                for e in events
            ],
            "next_cursor": next_cursor,
        }

    def wait_for_event(
        self,
        after_cursor: int = 0,
        session_key: Optional[str] = None,
        timeout_ms: int = 30000,
    ) -> Optional[dict]:
        """Block until a matching event arrives or timeout expires."""
        deadline = time.monotonic() + (timeout_ms / 1000.0)

        while time.monotonic() < deadline:
            with self._lock:
                for e in self._queue:
                    if e.cursor > after_cursor and (
                        not session_key or e.session_key == session_key
                    ):
                        return {
                            "cursor": e.cursor, "type": e.type,
                            "session_key": e.session_key, **e.data,
                        }

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            self._new_event.clear()
            self._new_event.wait(timeout=min(remaining, POLL_INTERVAL))

        return None

    def list_pending_approvals(self) -> List[dict]:
        """List approval requests observed during this bridge session."""
        with self._lock:
            return sorted(
                self._pending_approvals.values(),
                key=lambda a: a.get("created_at", ""),
            )

    def respond_to_approval(self, approval_id: str, decision: str) -> dict:
        """Resolve a pending approval (best-effort without gateway IPC)."""
        with self._lock:
            approval = self._pending_approvals.pop(approval_id, None)

        if not approval:
            return {"error": f"Approval not found: {approval_id}"}

        self._enqueue(QueueEvent(
            cursor=0,  # Will be set by _enqueue
            type="approval_resolved",
            session_key=approval.get("session_key", ""),
            data={"approval_id": approval_id, "decision": decision},
        ))

        return {"resolved": True, "approval_id": approval_id, "decision": decision}

    def _enqueue(self, event: QueueEvent) -> None:
        """Add an event to the queue and wake any waiters."""
        with self._lock:
            self._cursor += 1
            event.cursor = self._cursor
            self._queue.append(event)
            # Trim queue to limit
            while len(self._queue) > QUEUE_LIMIT:
                self._queue.pop(0)
        self._new_event.set()

    def _poll_loop(self):
        """Background loop: poll SessionDB for new messages."""
        db = _get_session_db()
        if not db:
            logger.warning("EventBridge: SessionDB unavailable, event polling disabled")
            return

        while self._running:
            try:
                self._poll_once(db)
            except Exception as e:
                logger.debug("EventBridge poll error: %s", e)
            time.sleep(POLL_INTERVAL)

    def _poll_once(self, db):
        """Check for new messages across all sessions.

        Uses mtime checks on sessions.json and state.db to skip work
        when nothing has changed — makes 200ms polling essentially free.
        """
        # Check if sessions.json has changed (mtime check is ~1μs)
        sessions_file = _get_sessions_dir() / "sessions.json"
        try:
            sj_mtime = sessions_file.stat().st_mtime if sessions_file.exists() else 0.0
        except OSError:
            sj_mtime = 0.0

        if sj_mtime != self._sessions_json_mtime:
            self._sessions_json_mtime = sj_mtime
            self._cached_sessions_index = _load_sessions_index()

        # Check if state.db has changed
        db_file = _resolve_hermes_home() / "state.db"

        try:
            db_mtime = db_file.stat().st_mtime if db_file.exists() else 0.0
        except OSError:
            db_mtime = 0.0

        if db_mtime == self._state_db_mtime and sj_mtime == self._sessions_json_mtime:
            return  # Nothing changed since last poll — skip entirely

        self._state_db_mtime = db_mtime
        entries = self._cached_sessions_index

        for session_key, entry in entries.items():
            session_id = entry.get("session_id", "")
            if not session_id:
                continue

            last_seen = self._last_poll_timestamps.get(session_key, 0.0)

            try:
                messages = db.get_messages(session_id)
            except Exception:
                continue

            if not messages:
                continue

            # Normalize timestamps to float for comparison
            def _ts_float(ts) -> float:
                if isinstance(ts, (int, float)):
                    return float(ts)
                if isinstance(ts, str) and ts:
                    try:
                        return float(ts)
                    except ValueError:
                        # ISO string — parse to epoch
                        try:
                            from datetime import datetime
                            return datetime.fromisoformat(ts).timestamp()
                        except Exception:
                            return 0.0
                return 0.0

            # Find messages newer than our last seen timestamp
            new_messages = []
            for msg in messages:
                ts = _ts_float(msg.get("timestamp", 0))
                role = msg.get("role", "")
                if role not in {"user", "assistant"}:
                    continue
                if ts > last_seen:
                    new_messages.append(msg)

            for msg in new_messages:
                content = _extract_message_content(msg)
                if not content:
                    continue
                self._enqueue(QueueEvent(
                    cursor=0,
                    type="message",
                    session_key=session_key,
                    data={
                        "role": msg.get("role", ""),
                        "content": content[:500],
                        "timestamp": str(msg.get("timestamp", "")),
                        "message_id": str(msg.get("id", "")),
                    },
                ))

            # Update last seen to the most recent message timestamp
            all_ts = [_ts_float(m.get("timestamp", 0)) for m in messages]
            if all_ts:
                latest = max(all_ts)
                if latest > last_seen:
                    self._last_poll_timestamps[session_key] = latest


# ---------------------------------------------------------------------------
# computer_use safety gate + result mapping (Fase 3)
#
# An external MCP client (Cursor, Claude Code, any other editor wired to
# this stdio server) driving the desktop is the largest prompt-injection
# surface `computer_use` has, so it is locked down harder here than the
# rest of this bridge's tool surface. Both helpers below are plain module
# functions (no `mcp` import at module scope) so the safety decision itself
# stays unit-testable even in environments where the `mcp` package isn't
# installed — only `_computer_use_result_to_mcp_content` needs it, and that
# import is deferred to the call site.
# ---------------------------------------------------------------------------

# Opt-in for non-safe (destructive) computer_use actions over MCP. Unset/
# falsy => only capture/wait/list_apps are reachable from this transport.
_COMPUTER_CONTROL_ALLOW_ENV = "SIMPLICIO_MCP_ALLOW_COMPUTER_CONTROL"


def _computer_control_allowed_via_env() -> bool:
    """True when the operator opted into non-safe computer_use actions over MCP."""
    from utils import env_var_enabled

    return env_var_enabled(_COMPUTER_CONTROL_ALLOW_ENV)


def _computer_use_mcp_refusal(action: str) -> Optional[str]:
    """Return a refusal message for ``action`` over the MCP surface, or ``None`` to allow.

    Two independent, defense-in-depth checks (``handle_computer_use`` itself
    also enforces the killswitch — see ``tools.computer_use.tool`` — so this
    is belt-and-suspenders, not the only gate):

      1. Safe-actions-only by default. Only ``capture`` / ``wait`` /
         ``list_apps`` (``tools.computer_use.tool._SAFE_ACTIONS``) run
         without an explicit opt-in. Everything else requires
         ``SIMPLICIO_MCP_ALLOW_COMPUTER_CONTROL`` to be truthy.
      2. The runtime killswitch is always honored for non-safe actions,
         opt-in or not — see ``tools.computer_use.killswitch``.
    """
    from tools.computer_use import killswitch
    from tools.computer_use.tool import _SAFE_ACTIONS

    normalized = (action or "").strip().lower()
    if normalized in _SAFE_ACTIONS:
        return None

    if not _computer_control_allowed_via_env():
        return (
            f"computer_use action {normalized!r} is disabled over MCP by "
            f"default — only capture/wait/list_apps are allowed from this "
            f"transport. Set {_COMPUTER_CONTROL_ALLOW_ENV}=1 in the "
            f"Simplicio Agent process environment to let an MCP client "
            f"drive the desktop."
        )

    if killswitch.is_paused():
        return (
            "Computer control is paused (killswitch). Resume it in "
            "Simplicio to continue."
        )

    return None


def _computer_use_result_to_mcp_content(result: Any) -> List[Any]:
    """Map ``handle_computer_use``'s return shape into MCP content blocks.

    ``handle_computer_use`` returns either a JSON string (text-only results:
    wait, key, list_apps, errors, ...) or a dict marked ``_multimodal``
    (screenshot + summary — see ``tools/computer_use/tool.py``'s module
    docstring for the exact envelope shape). FastMCP tool functions may
    return a list of content blocks directly and have them passed through
    as-is, so build that list explicitly instead of collapsing the
    screenshot into a text-only note.
    """
    from mcp.types import ImageContent, TextContent

    if isinstance(result, dict) and result.get("_multimodal"):
        blocks: List[Any] = []
        for part in result.get("content") or []:
            if not isinstance(part, dict):
                continue
            ptype = part.get("type")
            if ptype == "text":
                text = part.get("text") or ""
                if text:
                    blocks.append(TextContent(type="text", text=text))
            elif ptype == "image_url":
                url = (part.get("image_url") or {}).get("url") or ""
                header, _, b64 = url.partition(",")
                mime = "image/png"
                if header.startswith("data:"):
                    mime = header[len("data:"):].split(";")[0] or "image/png"
                if b64:
                    blocks.append(ImageContent(type="image", data=b64, mimeType=mime))
        if blocks:
            return blocks
        # A malformed/empty envelope shouldn't surface empty content.
        summary = result.get("text_summary") or "computer_use returned an empty result"
        return [TextContent(type="text", text=str(summary))]

    if isinstance(result, str):
        return [TextContent(type="text", text=result)]

    # Any other shape (shouldn't normally happen) — best-effort JSON dump so
    # the caller still gets something instead of a serialization crash.
    return [TextContent(type="text", text=_fast_dumps(result))]


# ---------------------------------------------------------------------------
# browser bridge (Fase 1, issue #98)
#
# Single action-dispatch tool mirroring the `computer_use` shape above,
# reusing `tools.browser_tool`'s existing per-action functions verbatim
# rather than reimplementing browser control. Every underlying function
# already returns a JSON string with an explicit "success"/"error" field
# (never raises for expected failure modes), so this layer's job is just
# argument validation + dispatch — never inventing a fake success.
# ---------------------------------------------------------------------------

_BROWSER_ACTIONS = {"navigate", "snapshot", "click", "type", "scroll", "vision", "console"}


def _browser_error(message: str) -> str:
    return _fast_dumps({"success": False, "error": message})


def _dispatch_browser_action(
    action: str,
    *,
    url: Optional[str] = None,
    ref: Optional[str] = None,
    text: Optional[str] = None,
    direction: Optional[str] = None,
    question: Optional[str] = None,
    annotate: bool = False,
    expression: Optional[str] = None,
    clear: bool = False,
    full: bool = False,
    task_id: Optional[str] = None,
) -> str:
    """Validate + dispatch one ``browser`` action. Returns a JSON string.

    Kept as a plain module function (no ``mcp`` import) so it stays unit
    testable without a running FastMCP server — same pattern as
    ``_computer_use_mcp_refusal`` above.
    """
    normalized = (action or "").strip().lower()
    if normalized not in _BROWSER_ACTIONS:
        return _browser_error(
            f"Unknown browser action {normalized!r}. Valid actions: "
            f"{sorted(_BROWSER_ACTIONS)}"
        )

    try:
        from tools import browser_tool as _bt
    except Exception as e:
        # Honest failure: the browser stack (agent-browser CLI, playwright,
        # etc.) isn't available on this install — never claim success.
        logger.debug("browser bridge: tools.browser_tool unavailable: %s", e)
        return _browser_error(f"Browser toolset is unavailable on this install: {e}")

    try:
        if normalized == "navigate":
            if not url:
                return _browser_error("browser action 'navigate' requires 'url'")
            return _bt.browser_navigate(url, task_id=task_id)

        if normalized == "snapshot":
            return _bt.browser_snapshot(full=bool(full), task_id=task_id)

        if normalized == "click":
            if not ref:
                return _browser_error("browser action 'click' requires 'ref'")
            return _bt.browser_click(ref, task_id=task_id)

        if normalized == "type":
            if not ref or text is None:
                return _browser_error("browser action 'type' requires 'ref' and 'text'")
            return _bt.browser_type(ref, text, task_id=task_id)

        if normalized == "scroll":
            if direction not in {"up", "down"}:
                return _browser_error(
                    f"browser action 'scroll' requires direction 'up' or 'down', got {direction!r}"
                )
            return _bt.browser_scroll(direction, task_id=task_id)

        if normalized == "vision":
            if not question:
                return _browser_error("browser action 'vision' requires 'question'")
            result = _bt.browser_vision(question, annotate=bool(annotate), task_id=task_id)
            return result if isinstance(result, str) else _fast_dumps(result)

        if normalized == "console":
            return _bt.browser_console(clear=bool(clear), expression=expression, task_id=task_id)
    except Exception as e:
        # Surface the real failure instead of swallowing it into a generic
        # success — e.g. no browser session started yet, backend crashed.
        logger.debug("browser bridge: action %r failed: %s", normalized, e)
        return _browser_error(f"browser action {normalized!r} failed: {e}")

    # Unreachable given the membership check above, but fail honestly
    # rather than falling through to an implicit None/success.
    return _browser_error(f"browser action {normalized!r} is not wired up")


# ---------------------------------------------------------------------------
# savings bridge (Fase 3, issue #98)
#
# Lets Hermes read the token-savings ledger and record new events without
# shelling out to `python -m agent.telemetry.savings_report` /
# `record_token_saving` via the terminal tool. Reuses the existing dormant
# telemetry stack documented in docs/mcp-telemetry.md verbatim.
# ---------------------------------------------------------------------------

_SAVINGS_ACTIONS = {"read", "record"}


def _savings_error(message: str) -> str:
    return _fast_dumps({"success": False, "error": message})


def _dispatch_savings_action(
    action: str,
    *,
    since: Optional[str] = None,
    raw_tokens: Optional[int] = None,
    compressed_tokens: Optional[int] = None,
    tool: Optional[str] = None,
    command: Optional[str] = None,
    adapter: Optional[str] = None,
    session: Optional[str] = None,
    repo: Optional[str] = None,
) -> str:
    """Validate + dispatch one ``savings`` action. Returns a JSON string."""
    normalized = (action or "").strip().lower()
    if normalized not in _SAVINGS_ACTIONS:
        return _savings_error(
            f"Unknown savings action {normalized!r}. Valid actions: "
            f"{sorted(_SAVINGS_ACTIONS)}"
        )

    try:
        from agent.telemetry.savings_report import build_report, parse_since
        from agent.telemetry.token_savings import iter_records, record_token_saving
    except Exception as e:
        logger.debug("savings bridge: telemetry stack unavailable: %s", e)
        return _savings_error(f"Savings telemetry is unavailable on this install: {e}")

    if normalized == "read":
        try:
            window = parse_since(since)
        except ValueError as e:
            return _savings_error(str(e))
        try:
            records = list(iter_records())
            report = build_report(records, since=window)
        except Exception as e:
            logger.debug("savings bridge: read failed: %s", e)
            return _savings_error(f"Failed to build savings report: {e}")
        return _fast_dumps({"success": True, "report": report}, indent=2)

    # action == "record"
    if raw_tokens is None or compressed_tokens is None:
        return _savings_error(
            "savings action 'record' requires 'raw_tokens' and 'compressed_tokens'"
        )
    try:
        record = record_token_saving(
            raw_tokens,
            compressed_tokens,
            tool=tool or "mcp",
            command=command or "unknown",
            adapter=adapter or "unknown",
            session=session or "unknown",
            repo=repo or "unknown",
        )
    except (TypeError, ValueError) as e:
        return _savings_error(f"Invalid savings record: {e}")
    except Exception as e:
        logger.debug("savings bridge: record failed: %s", e)
        return _savings_error(f"Failed to record savings event: {e}")

    return _fast_dumps(
        {"success": True, "recorded": _fast_loads(record.to_json())}, indent=2
    )


# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------


def _set_mcp_server_version(mcp: Any) -> None:
    """Expose the installed product version through MCP ``serverInfo``.

    FastMCP 1.26.0 does not accept a version in its public constructor, but
    its low-level server uses ``version`` when building initialize metadata.
    Keep the compatibility touchpoint isolated and harmless for test doubles
    or older SDKs that do not expose the private server object.
    """
    from hermes_cli import __version__

    low_level_server = getattr(mcp, "_mcp_server", None)
    if low_level_server is not None:
        low_level_server.version = __version__

def create_mcp_server(event_bridge: Optional[EventBridge] = None) -> "FastMCP":
    """Create and return the Simplicio Agent MCP server with all tools registered."""
    if not _MCP_SERVER_AVAILABLE:
        raise ImportError(
            "MCP server requires the 'mcp' package. "
            f"Install with: {sys.executable} -m pip install 'mcp'"
        )

    mcp = FastMCP(
        MCP_SERVER_NAME,
        instructions=(
            "Simplicio Agent is the sole public MCP gateway. Send natural-language "
            "intent to simplicio_act; use simplicio_capabilities only when explicit "
            "discovery is useful. The Agent reasons and coordinates, while its internal "
            "Simplicio Runtime performs execution. Messaging tools remain available."
        ),
    )
    _set_mcp_server_version(mcp)

    bridge = event_bridge or EventBridge()

    # -- universal autonomous Agent gateway ---------------------------------

    @mcp.tool()
    def simplicio_capabilities(
        query: str,
        workdir: Optional[str] = None,
        limit: int = 5,
    ) -> str:
        """Recall a compact set of Simplicio capabilities for an external intent.

        This is metadata-only and does not invoke a remote LLM. Most clients should
        call ``simplicio_act`` directly; the Agent performs this recall internally.
        """
        return _fast_dumps(
            rank_capabilities(query, workdir=workdir, limit=limit), indent=2
        )

    @mcp.tool()
    def simplicio_act(
        request: str,
        workdir: Optional[str] = None,
        client: str = "mcp",
        timeout_seconds: int = 900,
    ) -> str:
        """Ask the autonomous Simplicio Agent to complete any task.

        The gateway always runs with ``--yolo`` and the ``fast:fast`` profile.
        Hermes reasons and coordinates; all executable actions are delegated to the
        internal Simplicio Runtime. The MCP client receives the final result and
        evidence instead of managing Runtime commands itself.
        """
        return _fast_dumps(
            invoke_agent(
                request,
                workdir=workdir,
                client=client,
                timeout_seconds=timeout_seconds,
            ),
            indent=2,
        )

    # -- conversations_list ------------------------------------------------

    @mcp.tool()
    def conversations_list(
        platform: Optional[str] = None,
        limit: int = 50,
        search: Optional[str] = None,
    ) -> str:
        """List active messaging conversations across connected platforms.

        Returns conversations with their session keys (needed for messages_read),
        platform, chat type, display name, and last activity time.

        Args:
            platform: Filter by platform name (telegram, discord, slack, etc.)
            limit: Maximum number of conversations to return (default 50)
            search: Optional text to filter conversations by name
        """
        limit = _coerce_int(limit, default=50, minimum=1, maximum=200)
        entries = _load_sessions_index()
        conversations = []

        for key, entry in entries.items():
            origin = entry.get("origin", {})
            entry_platform = entry.get("platform") or origin.get("platform", "")

            if platform and entry_platform.lower() != platform.lower():
                continue

            display_name = entry.get("display_name", "")
            chat_name = origin.get("chat_name", "")
            if search:
                search_lower = search.lower()
                if (search_lower not in display_name.lower()
                        and search_lower not in chat_name.lower()
                        and search_lower not in key.lower()):
                    continue

            conversations.append({
                "session_key": key,
                "session_id": entry.get("session_id", ""),
                "platform": entry_platform,
                "chat_type": entry.get("chat_type", origin.get("chat_type", "")),
                "display_name": display_name,
                "chat_name": chat_name,
                "user_name": origin.get("user_name", ""),
                "updated_at": entry.get("updated_at", ""),
            })

        conversations.sort(key=lambda c: c.get("updated_at", ""), reverse=True)
        conversations = conversations[:limit]

        return _fast_dumps({
            "count": len(conversations),
            "conversations": conversations,
        }, indent=2)

    # -- conversation_get --------------------------------------------------

    @mcp.tool()
    def conversation_get(session_key: str) -> str:
        """Get detailed info about one conversation by its session key.

        Args:
            session_key: The session key from conversations_list
        """
        entries = _load_sessions_index()
        entry = entries.get(session_key)

        if not entry:
            return _fast_dumps({"error": f"Conversation not found: {session_key}"})

        origin = entry.get("origin", {})
        return _fast_dumps({
            "session_key": session_key,
            "session_id": entry.get("session_id", ""),
            "platform": entry.get("platform") or origin.get("platform", ""),
            "chat_type": entry.get("chat_type", origin.get("chat_type", "")),
            "display_name": entry.get("display_name", ""),
            "user_name": origin.get("user_name", ""),
            "chat_name": origin.get("chat_name", ""),
            "chat_id": origin.get("chat_id", ""),
            "thread_id": origin.get("thread_id"),
            "updated_at": entry.get("updated_at", ""),
            "created_at": entry.get("created_at", ""),
            "input_tokens": entry.get("input_tokens", 0),
            "output_tokens": entry.get("output_tokens", 0),
            "total_tokens": entry.get("total_tokens", 0),
        }, indent=2)

    # -- messages_read -----------------------------------------------------

    @mcp.tool()
    def messages_read(
        session_key: str,
        limit: int = 50,
    ) -> str:
        """Read recent messages from a conversation.

        Returns the message history in chronological order with role, content,
        and timestamp for each message.

        Args:
            session_key: The session key from conversations_list
            limit: Maximum number of messages to return (default 50, most recent)
        """
        limit = _coerce_int(limit, default=50, minimum=1, maximum=200)
        entries = _load_sessions_index()
        entry = entries.get(session_key)
        if not entry:
            return _fast_dumps({"error": f"Conversation not found: {session_key}"})

        session_id = entry.get("session_id", "")
        if not session_id:
            return _fast_dumps({"error": "No session ID for this conversation"})

        db = _get_session_db()
        if not db:
            return _fast_dumps({"error": "Session database unavailable"})

        try:
            all_messages = db.get_messages(session_id)
        except Exception as e:
            logger.debug("get_messages failed: %s", e)
            return _fast_dumps({"error": "Unable to read conversation history."})

        filtered = []
        for msg in all_messages:
            role = msg.get("role", "")
            if role in {"user", "assistant"}:
                content = _extract_message_content(msg)
                if content:
                    filtered.append({
                        "id": str(msg.get("id", "")),
                        "role": role,
                        "content": content[:2000],
                        "timestamp": msg.get("timestamp", ""),
                    })

        messages = filtered[-limit:]

        return _fast_dumps({
            "session_key": session_key,
            "count": len(messages),
            "total_in_session": len(filtered),
            "messages": messages,
        }, indent=2)

    # -- attachments_fetch -------------------------------------------------

    @mcp.tool()
    def attachments_fetch(
        session_key: str,
        message_id: str,
    ) -> str:
        """List non-text attachments for a message in a conversation.

        Extracts images, media files, and other non-text content blocks
        from the specified message.

        Args:
            session_key: The session key from conversations_list
            message_id: The message ID from messages_read
        """
        entries = _load_sessions_index()
        entry = entries.get(session_key)
        if not entry:
            return _fast_dumps({"error": f"Conversation not found: {session_key}"})

        session_id = entry.get("session_id", "")
        if not session_id:
            return _fast_dumps({"error": "No session ID for this conversation"})

        db = _get_session_db()
        if not db:
            return _fast_dumps({"error": "Session database unavailable"})

        try:
            all_messages = db.get_messages(session_id)
        except Exception as e:
            logger.debug("get_messages failed: %s", e)
            return _fast_dumps({"error": "Unable to read conversation history."})

        # Find the target message
        target_msg = None
        for msg in all_messages:
            if str(msg.get("id", "")) == message_id:
                target_msg = msg
                break

        if not target_msg:
            return _fast_dumps({"error": f"Message not found: {message_id}"})

        attachments = _extract_attachments(target_msg)

        return _fast_dumps({
            "message_id": message_id,
            "count": len(attachments),
            "attachments": attachments,
        }, indent=2)

    # -- events_poll -------------------------------------------------------

    @mcp.tool()
    def events_poll(
        after_cursor: int = 0,
        session_key: Optional[str] = None,
        limit: int = 20,
    ) -> str:
        """Poll for new conversation events since a cursor position.

        Returns events that have occurred since the given cursor. Use the
        returned next_cursor value for subsequent polls.

        Event types: message, approval_requested, approval_resolved

        Args:
            after_cursor: Return events after this cursor (0 for all)
            session_key: Optional filter to one conversation
            limit: Maximum events to return (default 20)
        """
        after_cursor = _coerce_int(after_cursor, default=0, minimum=0, maximum=10**18)
        limit = _coerce_int(limit, default=20, minimum=1, maximum=200)
        result = bridge.poll_events(
            after_cursor=after_cursor,
            session_key=session_key,
            limit=limit,
        )
        return _fast_dumps(result, indent=2)

    # -- events_wait -------------------------------------------------------

    @mcp.tool()
    def events_wait(
        after_cursor: int = 0,
        session_key: Optional[str] = None,
        timeout_ms: int = 30000,
    ) -> str:
        """Wait for the next conversation event (long-poll).

        Blocks until a matching event arrives or the timeout expires.
        Use this for near-real-time event delivery without polling.

        Args:
            after_cursor: Wait for events after this cursor
            session_key: Optional filter to one conversation
            timeout_ms: Maximum wait time in milliseconds (default 30000)
        """
        after_cursor = _coerce_int(after_cursor, default=0, minimum=0, maximum=10**18)
        timeout_ms = _coerce_int(
            timeout_ms,
            default=30000,
            minimum=0,
            maximum=300000,
        )  # Cap at 5 minutes
        event = bridge.wait_for_event(
            after_cursor=after_cursor,
            session_key=session_key,
            timeout_ms=timeout_ms,
        )
        if event:
            return _fast_dumps({"event": event}, indent=2)
        return _fast_dumps({"event": None, "reason": "timeout"}, indent=2)

    # -- messages_send -----------------------------------------------------

    @mcp.tool()
    def messages_send(
        target: str,
        message: str,
    ) -> str:
        """Send a message to a platform conversation.

        The target format is "platform:chat_id" — same format used by the
        channels_list tool. You can also use human-friendly channel names
        that will be resolved automatically.

        Examples:
            target="telegram:6308981865"
            target="discord:#general"
            target="slack:#engineering"

        Args:
            target: Platform target in "platform:identifier" format
            message: The message text to send
        """
        if not target or not message:
            return _fast_dumps({"error": "Both target and message are required"})

        try:
            from tools.send_message_tool import send_message_tool
            result_str = send_message_tool(
                {"action": "send", "target": target, "message": message}
            )
            return result_str
        except ImportError:
            return _fast_dumps({"error": "Send message capability is unavailable."})
        except Exception as e:
            logger.debug("send_message_tool failed: %s", e)
            return _fast_dumps({"error": "Failed to send message."})

    # -- channels_list -----------------------------------------------------

    @mcp.tool()
    def channels_list(platform: Optional[str] = None) -> str:
        """List available messaging channels and targets across platforms.

        Returns channels that you can send messages to. The target strings
        returned here can be used directly with the messages_send tool.

        Args:
            platform: Filter by platform name (telegram, discord, slack, etc.)
        """
        directory = _load_channel_directory()
        if not directory:
            entries = _load_sessions_index()
            targets = []
            seen = set()
            for key, entry in entries.items():
                origin = entry.get("origin", {})
                p = entry.get("platform") or origin.get("platform", "")
                chat_id = origin.get("chat_id", "")
                if not p or not chat_id:
                    continue
                if platform and p.lower() != platform.lower():
                    continue
                target_str = f"{p}:{chat_id}"
                if target_str in seen:
                    continue
                seen.add(target_str)
                targets.append({
                    "target": target_str,
                    "platform": p,
                    "name": entry.get("display_name") or origin.get("chat_name", ""),
                    "chat_type": entry.get("chat_type", origin.get("chat_type", "")),
                })
            return _fast_dumps({"count": len(targets), "channels": targets}, indent=2)

        channels = []
        for plat, entries_list in directory.get("platforms", {}).items():
            if platform and plat.lower() != platform.lower():
                continue
            if isinstance(entries_list, list):
                for ch in entries_list:
                    if isinstance(ch, dict):
                        chat_id = ch.get("id", ch.get("chat_id", ""))
                        channels.append({
                            "target": f"{plat}:{chat_id}" if chat_id else plat,
                            "platform": plat,
                            "name": ch.get("name", ch.get("display_name", "")),
                            "chat_type": ch.get("type", ""),
                        })

        return _fast_dumps({"count": len(channels), "channels": channels}, indent=2)

    # -- permissions_list_open ---------------------------------------------

    @mcp.tool()
    def permissions_list_open() -> str:
        """List pending approval requests observed during this bridge session.

        Returns exec and plugin approval requests that the bridge has seen
        since it started. Approvals are live-session only — older approvals
        from before the bridge connected are not included.
        """
        approvals = bridge.list_pending_approvals()
        return _fast_dumps({
            "count": len(approvals),
            "approvals": approvals,
        }, indent=2)

    # -- permissions_respond -----------------------------------------------

    @mcp.tool()
    def permissions_respond(
        id: str,
        decision: str,
    ) -> str:
        """Respond to a pending approval request.

        Args:
            id: The approval ID from permissions_list_open
            decision: One of "allow-once", "allow-always", or "deny"
        """
        if decision not in {"allow-once", "allow-always", "deny"}:
            return _fast_dumps({
                "error": f"Invalid decision: {decision}. "
                         f"Must be allow-once, allow-always, or deny"
            })

        result = bridge.respond_to_approval(id, decision)
        return _fast_dumps(result, indent=2)

    # -- browser -------------------------------------------------------
    #
    # Single action-dispatch tool — see `_dispatch_browser_action` above
    # for validation/dispatch and `tools.browser_tool` for the underlying
    # implementation (agent-browser CLI / Camofox / cloud provider).

    @mcp.tool()
    def browser(
        action: str,
        url: Optional[str] = None,
        ref: Optional[str] = None,
        text: Optional[str] = None,
        direction: Optional[str] = None,
        question: Optional[str] = None,
        annotate: Optional[bool] = None,
        expression: Optional[str] = None,
        clear: Optional[bool] = None,
        full: Optional[bool] = None,
        task_id: Optional[str] = None,
    ) -> str:
        """Drive the Simplicio Agent browser session.

        Stable actions: navigate, snapshot, click, type, scroll, vision,
        console. Each action returns a JSON string with an explicit
        "success" field — failures (no session started, backend crashed,
        blocked URL, ...) are returned as an honest "error" rather than a
        fabricated success.

        Args:
            action: navigate, snapshot, click, type, scroll, vision, or console.
            url: Target URL for action='navigate'.
            ref: Element reference from a snapshot (e.g. '@e5') for
                action='click' or action='type'.
            text: Text to type for action='type'.
            direction: 'up' or 'down' for action='scroll'.
            question: What to look for visually, for action='vision'.
            annotate: For action='vision' — overlay numbered element labels.
            expression: JavaScript to evaluate in the page for action='console'
                (omit to just read console output/errors).
            clear: For action='console' — clear buffers after reading.
            full: For action='snapshot' — return the complete page content
                instead of the compact interactive-elements view.
            task_id: Session isolation key (default session when omitted).
        """
        return _dispatch_browser_action(
            action,
            url=url,
            ref=ref,
            text=text,
            direction=direction,
            question=question,
            annotate=bool(annotate),
            expression=expression,
            clear=bool(clear),
            full=bool(full),
            task_id=task_id,
        )

    # -- computer_use --------------------------------------------------
    #
    # Safety-gated — see `_computer_use_mcp_refusal` above. Defaults to
    # SAFE ACTIONS ONLY (capture/wait/list_apps); every other action needs
    # SIMPLICIO_MCP_ALLOW_COMPUTER_CONTROL=1 AND an unpaused killswitch.
    # Reuses `tools.computer_use.tool.handle_computer_use` verbatim rather
    # than reimplementing action dispatch.

    @mcp.tool()
    def computer_use(
        action: str,
        mode: Optional[str] = None,
        app: Optional[str] = None,
        max_elements: Optional[int] = None,
        element: Optional[int] = None,
        coordinate: Optional[List[int]] = None,
        button: Optional[str] = None,
        modifiers: Optional[List[str]] = None,
        from_element: Optional[int] = None,
        to_element: Optional[int] = None,
        from_coordinate: Optional[List[int]] = None,
        to_coordinate: Optional[List[int]] = None,
        direction: Optional[str] = None,
        amount: Optional[int] = None,
        value: Optional[str] = None,
        text: Optional[str] = None,
        keys: Optional[str] = None,
        seconds: Optional[float] = None,
        raise_window: Optional[bool] = None,
        capture_after: Optional[bool] = None,
    ) -> List[Any]:
        """Drive the desktop in the background via cua-driver.

        Screenshots, mouse, keyboard, scroll, drag — without stealing the
        user's cursor or keyboard focus. Preferred workflow: call with
        action='capture' (mode='som' gives numbered element overlays), then
        click by `element` index.

        SAFETY: by default only capture/wait/list_apps run over MCP. Every
        other action is refused unless the Simplicio Agent process has
        SIMPLICIO_MCP_ALLOW_COMPUTER_CONTROL=1 set, and is refused
        regardless while the computer_use killswitch is paused (flip it
        from the Simplicio desktop app, or `PUT /api/tools/computer-use/pause`).

        Args:
            action: capture, click, double_click, right_click, middle_click,
                drag, scroll, type, key, set_value, wait, list_apps, or
                focus_app.
            mode: For action='capture' — 'som' (screenshot + numbered
                element overlays, default), 'vision' (plain screenshot), or
                'ax' (accessibility tree only, no image).
            app: Optional app name/bundle ID to scope the capture/action to.
                Pass 'screen' or 'desktop' for the OS shell surface.
            max_elements: Cap on the AX `elements` array from capture
                (default 100, max 1000).
            element: 1-based SOM index from the last capture — preferred
                click/scroll/drag target over raw coordinates.
            coordinate: [x, y] pixel target, only when no element index is
                available.
            button: Mouse button for click actions — left, right, or middle.
            modifiers: Modifier keys held during the action (cmd, shift,
                option/alt, ctrl, win, ...).
            from_element: Source element index for action='drag'.
            to_element: Target element index for action='drag'.
            from_coordinate: Source [x, y] for action='drag'.
            to_coordinate: Target [x, y] for action='drag'.
            direction: Scroll direction — up, down, left, right.
            amount: Scroll wheel ticks (default 3).
            value: New value for action='set_value' (dropdown label or
                slider value).
            text: Text to type for action='type'.
            keys: Key combo for action='key', e.g. 'cmd+s', 'escape'.
            seconds: Seconds to wait for action='wait' (max 30).
            raise_window: For action='focus_app' — bring the window to
                front (disrupts the user). Default false.
            capture_after: If true, include a follow-up capture in the
                response after the action runs.
        """
        refusal = _computer_use_mcp_refusal(action)
        if refusal is not None:
            from mcp.types import TextContent

            return [TextContent(type="text", text=_fast_dumps({"error": refusal}))]

        from tools.computer_use.tool import handle_computer_use

        call_args = {
            "action": action,
            "mode": mode,
            "app": app,
            "max_elements": max_elements,
            "element": element,
            "coordinate": coordinate,
            "button": button,
            "modifiers": modifiers,
            "from_element": from_element,
            "to_element": to_element,
            "from_coordinate": from_coordinate,
            "to_coordinate": to_coordinate,
            "direction": direction,
            "amount": amount,
            "value": value,
            "text": text,
            "keys": keys,
            "seconds": seconds,
            "raise_window": raise_window,
            "capture_after": capture_after,
        }
        # Drop unset optional params rather than passing them through as
        # explicit Nones — handle_computer_use / _dispatch read some of
        # these via `args.get(key, default)`, which only falls back to
        # `default` when the key is ABSENT, not when it's present-but-None.
        call_args = {k: v for k, v in call_args.items() if v is not None}
        result = handle_computer_use(call_args)
        return _computer_use_result_to_mcp_content(result)

    # -- low-frequency-domain bridges (cron/gateway/hooks + CLI-fallback
    # contract for workflow/issue-factory/agent/desktop/plan-decide-sprint-
    # learn/doctor-tokio-health-settings) — see issue #99 and
    # docs/mcp-low-frequency-bridges.md. Kept in a separate module so those
    # tools stay independently testable without booting this whole server.

    from mcp_low_freq_bridges import register_low_freq_tools

    register_low_freq_tools(mcp)

    # -- savings ---------------------------------------------------------
    #
    # Read/record the token-savings ledger (see docs/mcp-telemetry.md) so
    # Hermes can close the post-task loop without shelling out to
    # `python -m agent.telemetry.savings_report` / `record_token_saving`.

    @mcp.tool()
    def savings(
        action: str,
        since: Optional[str] = None,
        raw_tokens: Optional[int] = None,
        compressed_tokens: Optional[int] = None,
        tool: Optional[str] = None,
        command: Optional[str] = None,
        adapter: Optional[str] = None,
        session: Optional[str] = None,
        repo: Optional[str] = None,
    ) -> str:
        """Read or record Simplicio's token-savings telemetry.

        action='read' aggregates the JSONL savings ledger into a report
        (same shape as `simplicio-savings-report --json`). action='record'
        appends one savings event to the ledger. Both return a JSON string
        with an explicit "success" field; missing/invalid arguments or an
        unavailable telemetry stack are reported as an honest "error".

        Args:
            action: 'read' or 'record'.
            since: For action='read' — time window, e.g. '7d', '24h', '2w'
                (default '7d').
            raw_tokens: For action='record' — tokens the raw approach would
                have used.
            compressed_tokens: For action='record' — tokens actually spent.
            tool: For action='record' — the tool/capability name (default
                'mcp').
            command: For action='record' — the command/verb invoked.
            adapter: For action='record' — the LLM adapter/provider used.
            session: For action='record' — the session identifier.
            repo: For action='record' — the repo/project identifier.
        """
        return _dispatch_savings_action(
            action,
            since=since,
            raw_tokens=raw_tokens,
            compressed_tokens=compressed_tokens,
            tool=tool,
            command=command,
            adapter=adapter,
            session=session,
            repo=repo,
        )

    return mcp


# ---------------------------------------------------------------------------
# Subscription gate
# ---------------------------------------------------------------------------

# Env escape hatch for self-hosted / dev / CI installs that run the runtime
# without a Nous Portal login. Any truthy value bypasses the subscription
# check. The hosted product leaves this unset so access stays subscription-only.
_UNLICENSED_BYPASS_ENV = "SIMPLICIO_MCP_ALLOW_UNLICENSED"
_MCP_CAPABILITY = "the Simplicio Agent MCP server"


def _subscription_gate() -> Optional[str]:
    """Verify the caller has active Simplicio subscription access.

    Returns ``None`` when access is granted, or a user-facing message
    explaining why it was denied. Access is granted when the
    ``SIMPLICIO_MCP_ALLOW_UNLICENSED`` env var is truthy (self-hosted / dev),
    or when the Nous Portal account has paid service access or a live tool
    pool. Reuses the existing entitlement chain in ``hermes_cli.nous_account``
    so there is a single source of truth for what "subscribed" means.

    The MCP server is a paid product surface, so an unverifiable entitlement
    is denied (fail-closed) rather than allowed.
    """
    bypass = os.environ.get(_UNLICENSED_BYPASS_ENV, "").strip().lower()
    if bypass in {"1", "true", "yes", "on"}:
        logger.warning("Subscription gate bypassed via %s", _UNLICENSED_BYPASS_ENV)
        return None

    try:
        from hermes_cli.nous_account import (
            format_nous_portal_entitlement_message,
            get_nous_portal_account_info,
        )
    except Exception as e:
        logger.debug("entitlement module unavailable: %s", e)
        return (
            f"{_MCP_CAPABILITY} requires an active Simplicio subscription, which "
            f"could not be verified on this install. Log in with "
            f"`simplicio-agent model`, or set {_UNLICENSED_BYPASS_ENV}=1 to run "
            f"self-hosted."
        )

    try:
        # Default (force_fresh=False) trusts a valid, unexpired portal-signed
        # JWT as a local entitlement snapshot and only hits the network when the
        # JWT is absent/expired. A free user cannot forge the signed `paid_access`
        # claim, and this keeps paying subscribers working through a transient
        # portal/network blip instead of being denied on every startup.
        info = get_nous_portal_account_info()
    except Exception as e:
        logger.debug("account lookup failed: %s", e)
        info = None

    # Returns None when entitled; a denial message otherwise.
    return format_nous_portal_entitlement_message(info, capability=_MCP_CAPABILITY)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run_mcp_server(verbose: bool = False) -> None:
    """Start the Simplicio Agent MCP server on stdio."""
    if not _MCP_SERVER_AVAILABLE:
        print(
            "Error: MCP server requires the 'mcp' package.\n"
            f"Install with: {sys.executable} -m pip install 'mcp'",
            file=sys.stderr,
        )
        sys.exit(1)

    if verbose:
        logging.basicConfig(level=logging.DEBUG, stream=sys.stderr)
    else:
        logging.basicConfig(level=logging.WARNING, stream=sys.stderr)

    denial = _subscription_gate()
    if denial is not None:
        print(f"Simplicio Agent: {denial}", file=sys.stderr)
        sys.exit(1)

    bridge = EventBridge()
    bridge.start()

    server = create_mcp_server(event_bridge=bridge)

    import asyncio

    async def _run():
        try:
            await server.run_stdio_async()
        finally:
            bridge.stop()

    # Install the faster uvloop event-loop policy when available (no-op on
    # Windows or when the optional dep isn't installed). Must run before the
    # loop is created by asyncio.run(). See agent/uvloop_utils.py.
    try:
        from agent.uvloop_utils import install_uvloop_policy

        install_uvloop_policy()
    except Exception:
        pass

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        bridge.stop()
