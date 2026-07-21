"""Structured provenance contracts for the existing reviewer paths."""

from agent.background_review import build_background_review_verdict
from agent.curator import build_curator_watcher_verdict


def test_background_review_is_explicitly_unverified_without_recomputation():
    verdict = build_background_review_verdict(["memory write requested"])

    assert verdict["schema"] == "simplicio.watcher-verdict/v1"
    assert verdict["verdict"] == "UNVERIFIED"
    assert verdict["provenance"] == "UNVERIFIED"
    assert verdict["matches"] is False
    assert verdict["action_count"] == 1


def test_curator_is_explicitly_unverified_without_recomputation():
    verdict = build_curator_watcher_verdict()

    assert verdict["schema"] == "simplicio.watcher-verdict/v1"
    assert verdict["verdict"] == "UNVERIFIED"
    assert verdict["provenance"] == "UNVERIFIED"
    assert verdict["matches"] is False
