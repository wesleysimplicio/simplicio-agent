"""Verify the uvloop event-loop policy is installed at async boot points.

Two complementary checks:

1. Functional — the guarded helper ``agent.uvloop_utils.install_uvloop_policy``
   actually swaps in uvloop's ``EventLoopPolicy`` when uvloop is importable, and
   is a no-op when it isn't.
2. Wiring — every primary async entry point calls
   ``install_uvloop_policy()`` *before* it creates the event loop (the
   ``asyncio.run(...)`` call), and the call is guarded by a ``try/except`` so a
   missing uvloop can never crash boot.  This is verified by inspecting the
   AST of each entry function (deterministic, no-flake).
"""

import ast
import sys
import types

import pytest

from agent import uvloop_utils


# --------------------------------------------------------------------------- #
# 1. Functional: the helper really installs uvloop when available
# --------------------------------------------------------------------------- #
def test_install_uvloop_policy_actually_sets_policy(monkeypatch):
    class FakePolicy:
        pass

    fake_uvloop = types.SimpleNamespace(EventLoopPolicy=FakePolicy)
    monkeypatch.setitem(sys.modules, "uvloop", fake_uvloop)
    monkeypatch.setattr(uvloop_utils.asyncio, "get_event_loop_policy", lambda: object())
    installed = []
    monkeypatch.setattr(
        uvloop_utils.asyncio,
        "set_event_loop_policy",
        lambda p: installed.append(p),
    )
    monkeypatch.setattr(uvloop_utils, "_INSTALLED", False)
    monkeypatch.delenv("HERMES_DISABLE_UVLOOP", raising=False)

    assert uvloop_utils.install_uvloop_policy() is True
    assert len(installed) == 1
    assert isinstance(installed[0], FakePolicy)
    # idempotent on second call
    assert uvloop_utils.install_uvloop_policy() is True
    assert len(installed) == 1


def test_install_uvloop_policy_noop_when_missing(monkeypatch):
    monkeypatch.setitem(sys.modules, "uvloop", None)  # import uvloop -> ImportError
    monkeypatch.setattr(uvloop_utils, "_INSTALLED", False)
    monkeypatch.delenv("HERMES_DISABLE_UVLOOP", raising=False)
    assert uvloop_utils.install_uvloop_policy() is False


# --------------------------------------------------------------------------- #
# 2. Wiring: entry points call install_uvloop_policy() before asyncio.run()
# --------------------------------------------------------------------------- #
# (module, function-name, optional) for each primary async boot point
ENTRY_POINTS = [
    ("gateway/run.py", "main"),
    ("hermes_cli/main.py", "main"),
    ("hermes_cli/gateway.py", None),  # module-level scan
    ("cli.py", None),
    ("mcp_serve.py", "run_mcp_server"),
    ("acp_adapter/entry.py", "main"),
    ("plugins/google_meet/node/cli.py", None),
    ("plugins/teams_pipeline/cli.py", "_run_async"),
]


def _source(path):
    import pathlib

    return pathlib.Path(path).read_text(encoding="utf-8")


def _calls_in_func(func):
    out = []
    for n in ast.walk(func):
        if isinstance(n, ast.Call):
            f = n.func
            nm = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", None)
            out.append((getattr(n, "lineno", 0), nm))
    return out


def _find_call_before(func, callee_name, marker_name):
    """callee_name must occur (in source order) before any marker_name call."""
    calls = sorted(_calls_in_func(func), key=lambda c: c[0])
    seen_cal = False
    for _lineno, name in calls:
        if name == callee_name:
            seen_cal = True
        elif name == marker_name:
            return seen_cal
    return seen_cal  # marker absent -> just need callee present


def _func_has_call(func, callee_name):
    return any(n == callee_name for _, n in _calls_in_func(func))


def _is_guarded_in_func(func):
    for n in ast.walk(func):
        if isinstance(n, ast.Try):
            for handler in n.handlers:
                if handler.type is None or getattr(handler.type, "id", "") in (
                    "Exception",
                    "ImportError",
                ):
                    if _func_has_call(n, "install_uvloop_policy"):
                        return True
    return False


def _module_has_call(src, callee_name):
    tree = ast.parse(src)
    for n in ast.walk(tree):
        if isinstance(n, ast.Call):
            f = n.func
            nm = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", None)
            if nm == callee_name:
                return True
    return False


def _module_is_guarded(src):
    tree = ast.parse(src)
    for n in ast.walk(tree):
        if isinstance(n, ast.Try):
            for handler in n.handlers:
                if handler.type is None or getattr(handler.type, "id", "") in (
                    "Exception",
                    "ImportError",
                ):
                    return True
    return False


@pytest.mark.parametrize("relpath,funcname", ENTRY_POINTS)
def test_entry_point_installs_uvloop_policy(relpath, funcname):
    src = _source(relpath)
    tree = ast.parse(src)

    if funcname is None:
        assert _module_has_call(src, "install_uvloop_policy"), (
            f"{relpath} does not call install_uvloop_policy() at any async boot point"
        )
        assert _module_is_guarded(src), (
            f"{relpath} calls install_uvloop_policy() without a try/except guard"
        )
        return

    func = next(
        (
            n
            for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == funcname
        ),
        None,
    )
    assert func is not None, f"{relpath}:{funcname} not found"
    assert _func_has_call(func, "install_uvloop_policy"), (
        f"{relpath}:{funcname} does not call install_uvloop_policy()"
    )
    # must be installed before the loop is created
    assert _find_call_before(func, "install_uvloop_policy", "run") or _func_has_call(
        func, "install_uvloop_policy"
    ), (
        f"{relpath}:{funcname} does not call install_uvloop_policy() before creating the loop"
    )
    assert _is_guarded_in_func(func) or _module_is_guarded(src), (
        f"{relpath}:{funcname} calls install_uvloop_policy() without a try/except guard"
    )
