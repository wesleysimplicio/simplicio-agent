import pytest

from agent.autobiographical_memory import (
    AutobiographicalStore,
    CausalEvidence,
    EpisodeFact,
    EpisodeManifest,
    MemoryKind,
    MemoryScope,
)
from agent.prediction_receipts import prediction_evidence_digest


PREDICTION = "a" * 64
OUTCOME = "b" * 64
CONSENT = "c" * 64


def _fact(
    summary: str = "User alice@example.com set token=secret-value",
) -> EpisodeFact:
    return EpisodeFact(
        key="delivery.preference",
        summary=summary,
        kind=MemoryKind.SEMANTIC,
        evidence=CausalEvidence(PREDICTION, OUTCOME, "prediction_observed"),
        confidence=0.9,
        personal=True,
        user_preference=True,
        consent_receipt=CONSENT,
    )


def _manifest(episode_id: str, fact: EpisodeFact, **changes: object) -> EpisodeManifest:
    values = {
        "episode_id": episode_id,
        "scope": MemoryScope.USER_PROJECT,
        "completed_verified": True,
        "valid_from": 10,
        "facts": (fact,),
    }
    values.update(changes)
    return EpisodeManifest(**values)  # type: ignore[arg-type]


def test_consolidation_is_causal_privacy_safe_and_bitemporal() -> None:
    store = AutobiographicalStore()

    (memory,) = store.consolidate(_manifest("episode-1", _fact()), system_time=20)

    assert memory.provenance == (PREDICTION, OUTCOME, CONSENT)
    assert "alice@example.com" not in memory.summary
    assert "secret-value" not in memory.summary
    assert memory.valid_from == 10
    assert memory.system_time == 20
    assert store.recall("delivery.preference", scope=MemoryScope.USER_PROJECT).known


def test_unverified_external_poisoned_and_cross_scope_facts_do_not_promote() -> None:
    store = AutobiographicalStore()
    fact = _fact()

    assert not store.consolidate(
        _manifest("unverified", fact, completed_verified=False), system_time=20
    )
    assert not store.consolidate(
        _manifest("external", fact, scope=MemoryScope.EXTERNAL), system_time=20
    )
    assert not store.consolidate(
        _manifest("helo", fact, scope=MemoryScope.RUNTIME_SELF), system_time=20
    )


def test_conflict_supersedes_and_revocation_makes_recall_unknown() -> None:
    store = AutobiographicalStore()
    (old,) = store.consolidate(
        _manifest("episode-1", _fact("Use email")), system_time=20
    )
    (new,) = store.consolidate(
        _manifest("episode-2", _fact("Use webhook")), system_time=30
    )

    assert new.supersedes == old.memory_id
    assert not next(
        memory for memory in store.memories if memory.memory_id == old.memory_id
    ).active
    store.revoke(new.memory_id, system_time=40)
    assert not store.recall("delivery.preference", scope=MemoryScope.USER_PROJECT).known


def test_replayed_episode_is_idempotent_and_never_self_supersedes() -> None:
    store = AutobiographicalStore()
    manifest = _manifest("episode-1", _fact("Use email"))
    (memory,) = store.consolidate(manifest, system_time=20)

    assert store.consolidate(manifest, system_time=30) == ()
    assert store.memories == (memory,)
    assert memory.active
    assert memory.supersedes == ""


def test_episode_id_collision_preserves_existing_lineage() -> None:
    store = AutobiographicalStore()
    (memory,) = store.consolidate(
        _manifest("episode-1", _fact("Use email")), system_time=20
    )

    with pytest.raises(ValueError, match="causal lineage"):
        store.consolidate(_manifest("episode-1", _fact("Use webhook")), system_time=30)

    assert store.memories == (memory,)
    assert store.recall(
        "delivery.preference", scope=MemoryScope.USER_PROJECT
    ).memories == (memory,)


def test_prediction_evidence_digest_is_stable_and_non_disclosing() -> None:
    from tests.agent.test_prediction_receipts import _receipt

    receipt = _receipt(action_digest="send token=do-not-leak")
    digest = prediction_evidence_digest(receipt)

    assert len(digest) == 64
    assert digest == prediction_evidence_digest(receipt)
    assert "do-not-leak" not in digest
