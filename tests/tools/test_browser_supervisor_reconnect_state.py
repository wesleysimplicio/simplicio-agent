"""Focused reconnect-state guards for the persistent browser supervisor."""

from __future__ import annotations

import asyncio

from tools import browser_supervisor as bs
from tools.browser_supervisor import CDPSupervisor, PendingDialog


class _Watchdog:
    def __init__(self) -> None:
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True


def test_reconnect_drops_stale_pending_dialog_and_watchdog() -> None:
    """A modal from the dead CDP session must not survive reattachment."""
    supervisor = CDPSupervisor(task_id="desktop", cdp_url="ws://browser.test")
    stale_dialog = PendingDialog(
        id="d-1",
        type="confirm",
        message="Leave page?",
        default_prompt="",
        opened_at=1.0,
        cdp_session_id="stale-session",
    )
    watchdog = _Watchdog()
    supervisor._page_session_id = "stale-session"
    supervisor._child_sessions["stale-child"] = {"target_id": "target-1"}
    supervisor._pending_dialogs[stale_dialog.id] = stale_dialog
    supervisor._dialog_watchdogs[stale_dialog.id] = watchdog  # type: ignore[assignment]

    supervisor._reset_connection_state_for_reconnect()

    assert supervisor._page_session_id is None
    assert supervisor._child_sessions == {}
    assert supervisor.snapshot().pending_dialogs == ()
    assert supervisor._dialog_watchdogs == {}
    assert watchdog.cancelled is True


def test_socket_drop_resets_modal_state_before_reconnect(monkeypatch) -> None:
    """The reconnect loop must apply the stale-modal reset after a drop."""
    supervisor = CDPSupervisor(task_id="desktop", cdp_url="ws://browser.test")
    stale_dialog = PendingDialog(
        id="d-1",
        type="alert",
        message="Old connection",
        default_prompt="",
        opened_at=1.0,
        cdp_session_id="stale-session",
    )
    watchdog = _Watchdog()
    supervisor._pending_dialogs[stale_dialog.id] = stale_dialog
    supervisor._dialog_watchdogs[stale_dialog.id] = watchdog  # type: ignore[assignment]

    class _WebSocket:
        async def close(self) -> None:
            return None

    async def connect(*_args, **_kwargs):
        return _WebSocket()

    async def attach() -> None:
        supervisor._page_session_id = "stale-session"

    async def read_until_drop() -> None:
        supervisor._stop_requested = True

    monkeypatch.setattr(bs.websockets, "connect", connect)
    monkeypatch.setattr(supervisor, "_attach_initial_page", attach)
    monkeypatch.setattr(supervisor, "_read_loop", read_until_drop)

    asyncio.run(supervisor._run())

    assert supervisor._page_session_id is None
    assert supervisor.snapshot().pending_dialogs == ()
    assert supervisor._dialog_watchdogs == {}
    assert watchdog.cancelled is True
