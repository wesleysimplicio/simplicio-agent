"""context.toon_prompts is read ONCE at session start and pinned (issue #16).

Toggling the TOON/JSON wire format for tool results mid-conversation would
change bytes the model has already seen (a message it already read as JSON
would suddenly look different if compressed/replayed), invalidating the
upstream prompt cache — "prompt caching is sacred" (AGENTS.md). This asserts
the flag is captured once at ``AIAgent`` construction (``agent_init.py``)
and never re-derived from config afterward, even if config.yaml changes
between two agent instances or the same instance runs many turns.
"""

from __future__ import annotations

import copy
import os
from unittest.mock import patch

import hermes_cli.config as cfgmod


def _build_agent(toon_prompts: bool):
    orig_load = cfgmod.load_config

    def _fake_load(*a, **k):
        cfg = copy.deepcopy(orig_load(*a, **k))
        cfg.setdefault("context", {})["toon_prompts"] = toon_prompts
        return cfg

    with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}):
        from run_agent import AIAgent

        with patch.object(cfgmod, "load_config", _fake_load):
            return AIAgent(
                api_key="test-key",
                base_url="https://openrouter.ai/api/v1",
                model="test/model",
                quiet_mode=True,
                skip_context_files=True,
                skip_memory=True,
            )


def test_flag_defaults_off():
    agent = _build_agent(toon_prompts=False)
    assert agent._toon_prompts_enabled is False


def test_flag_pinned_true_when_config_says_true():
    agent = _build_agent(toon_prompts=True)
    assert agent._toon_prompts_enabled is True


def test_flag_does_not_change_after_construction_even_if_config_changes():
    """The defining guarantee: a live agent's pinned value survives a
    config change that would affect a *new* agent instance."""
    agent_true = _build_agent(toon_prompts=True)
    assert agent_true._toon_prompts_enabled is True

    # Simulate config.yaml changing while agent_true's session is still
    # live (a user editing config.yaml mid-conversation, or a second
    # session starting with different settings).
    agent_false = _build_agent(toon_prompts=False)
    assert agent_false._toon_prompts_enabled is False

    # The first agent's already-pinned flag must be untouched.
    assert agent_true._toon_prompts_enabled is True


def test_no_config_read_happens_outside_construction():
    """agent.toon_boundary and agent.system_prompt must read the pinned
    instance attribute, never call load_config() themselves — otherwise a
    long-running conversation could pick up a config change mid-session.

    Only the mutating ``load_config()`` (which can run migrations and write
    to disk) is disallowed here. ``load_config_readonly()`` is a distinct,
    side-effect-free accessor used elsewhere (e.g. system_prompt.py's
    Telegram rich-messages hint) for config keys that have nothing to do
    with the TOON pin, so a bare substring match on "load_config" is too
    broad — it would false-positive on any unrelated use of the readonly
    variant.
    """
    import inspect
    import re

    import agent.toon_boundary as boundary
    import agent.system_prompt as system_prompt

    src_boundary = inspect.getsource(boundary)
    src_prompt = inspect.getsource(system_prompt)
    _mutating_load_config = re.compile(r"(?<!_)load_config\s*\(")
    assert not _mutating_load_config.search(src_boundary)
    assert not _mutating_load_config.search(src_prompt)
