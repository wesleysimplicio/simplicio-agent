"""Tests for the api-call ceiling resolution (Slice A — speed, issue #244).

Context: gateway.log showed turns needing >90 API calls stopped dead at the
blind `max_iterations=90` cap even when the iteration budget still had room.
`resolve_max_iterations` lets an operator lift that ceiling via env vars
without code changes, while leaving unconfigured behaviour identical (90).

These tests exercise the pure helper directly — no agent instantiation needed.
"""
from __future__ import annotations

import importlib

import pytest

from agent.iteration_budget import resolve_max_iterations


def _with_env(env: dict, fn):
    """Run ``fn`` with ``env`` overriding os.environ, then restore."""
    import os

    saved = {k: os.environ.get(k) for k in env}
    for k, v in env.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    try:
        return fn()
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_default_unchanged_when_env_unset():
    """(a) With no env vars, 90 stays 90."""

    def fn():
        return resolve_max_iterations(90)

    assert _with_env(
        {"HERMES_MAX_ITERATIONS": None, "HERMES_MAX_ITERATIONS_HEADROOM": None},
        fn,
    ) == 90


def test_env_override_absolute():
    """(b) HERMES_MAX_ITERATIONS=200 lifts the ceiling to 200."""

    def fn():
        return resolve_max_iterations(90)

    assert _with_env({"HERMES_MAX_ITERATIONS": "200"}, fn) == 200


def test_env_headroom_stretches():
    """(c) HERMES_MAX_ITERATIONS_HEADROOM=2.0 doubles the ceiling."""

    def fn():
        return resolve_max_iterations(90)

    assert _with_env({"HERMES_MAX_ITERATIONS_HEADROOM": "2.0"}, fn) == 180


def test_malformed_env_ignored():
    """Bad env input falls back to the caller's value (no crash, no change)."""

    def fn():
        return resolve_max_iterations(90)

    assert _with_env({"HERMES_MAX_ITERATIONS": "not-an-int"}, fn) == 90
    assert _with_env({"HERMES_MAX_ITERATIONS_HEADROOM": "bad"}, fn) == 90


def test_headroom_below_one_is_noop():
    """Headroom <= 1.0 must not shrink the ceiling."""

    def fn():
        return resolve_max_iterations(90)

    assert _with_env({"HERMES_MAX_ITERATIONS_HEADROOM": "0.5"}, fn) == 90


def test_override_and_headroom_combine():
    """Override then headroom: 200 * 1.5 = 300."""
    import os

    saved = {k: os.environ.get(k) for k in ("HERMES_MAX_ITERATIONS", "HERMES_MAX_ITERATIONS_HEADROOM")}
    os.environ["HERMES_MAX_ITERATIONS"] = "200"
    os.environ["HERMES_MAX_ITERATIONS_HEADROOM"] = "1.5"
    try:
        assert resolve_max_iterations(90) == 300
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
