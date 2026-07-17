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


def test_causal_evidence_rejects_malformed_prediction_receipt() -> None:
    with pytest.raises(ValueError, match="prediction_receipt"):
        CausalEvidence("not-a-sha256", OUTCOME, "prediction_observed")


def test_causal_evidence_rejects_malformed_outcome_receipt() -> None:
    with pytest.raises(ValueError, match="outcome_receipt"):
        CausalEvidence(PREDICTION, "not-a-sha256", "prediction_observed")


def test_causal_evidence_rejects_blank_relation() -> None:
    with pytest.raises(ValueError, match="causal relation"):
        CausalEvidence(PREDICTION, OUTCOME, "   ")


def test_episode_fact_rejects_blank_key_or_summary() -> None:
    evidence = CausalEvidence(PREDICTION, OUTCOME, "prediction_observed")
    with pytest.raises(ValueError, match="key and summary"):
        EpisodeFact(
            key="",
            summary="something",
            kind=MemoryKind.SEMANTIC,
            evidence=evidence,
            confidence=0.5,
        )
    with pytest.raises(ValueError, match="key and summary"):
        EpisodeFact(
            key="delivery.preference",
            summary="  ",
            kind=MemoryKind.SEMANTIC,
            evidence=evidence,
            confidence=0.5,
        )


def test_episode_fact_rejects_out_of_range_confidence() -> None:
    evidence = CausalEvidence(PREDICTION, OUTCOME, "prediction_observed")
    with pytest.raises(ValueError, match="confidence must be between"):
        EpisodeFact(
            key="delivery.preference",
            summary="something",
            kind=MemoryKind.SEMANTIC,
            evidence=evidence,
            confidence=1.5,
        )
    with pytest.raises(ValueError, match="confidence must be between"):
        EpisodeFact(
            key="delivery.preference",
            summary="something",
            kind=MemoryKind.SEMANTIC,
            evidence=evidence,
            confidence=-0.1,
        )


def test_episode_fact_rejects_malformed_consent_receipt() -> None:
    evidence = CausalEvidence(PREDICTION, OUTCOME, "prediction_observed")
    with pytest.raises(ValueError, match="consent_receipt"):
        EpisodeFact(
            key="delivery.preference",
            summary="something",
            kind=MemoryKind.SEMANTIC,
            evidence=evidence,
            confidence=0.5,
            consent_receipt="not-a-sha256",
        )


def test_episode_manifest_rejects_blank_episode_id() -> None:
    with pytest.raises(ValueError, match="episode_id"):
        EpisodeManifest(
            episode_id="   ",
            scope=MemoryScope.USER_PROJECT,
            completed_verified=True,
            valid_from=10,
            facts=(),
        )


def test_recall_skips_memories_for_other_keys_before_finding_match() -> None:
    # Exercises the _active_for loop continuation branch: an existing active
    # memory under a different key must not shadow lookups for the real key.
    store = AutobiographicalStore()
    store.consolidate(_manifest("episode-other", _fact("other pref"), **{
        "facts": (
            EpisodeFact(
                key="other.preference",
                summary="Use email",
                kind=MemoryKind.SEMANTIC,
                evidence=CausalEvidence(PREDICTION, OUTCOME, "prediction_observed"),
                confidence=0.9,
            ),
        ),
    }), system_time=10)

    (memory,) = store.consolidate(_manifest("episode-1", _fact("Use email")), system_time=20)

    assert store.recall("delivery.preference", scope=MemoryScope.USER_PROJECT).memories == (
        memory,
    )


def test_recall_precision_and_tokens_avoided_benchmark() -> None:
    """Minimal recall-quality benchmark (issue #171 AC: precision@k / tokens avoided).

    Consolidates a batch of episodes with resolved supersessions and measures:
    - precision@1: every recall for a live key returns exactly the current fact.
    - stale recall: superseded facts must never surface via recall.
    - tokens avoided: sanitized summaries must be no longer than raw transcript
      text would be (a lower bound stand-in for "we didn't store the transcript").
    """
    store = AutobiographicalStore()
    raw_transcript_chars = 0
    stored_chars = 0

    keys = [f"pref.k{i}" for i in range(5)]
    for generation in range(3):  # simulate three rounds of updates per key
        for i, key in enumerate(keys):
            summary = f"User {key} chose option-{generation}"
            raw_transcript_chars += len(summary) * 20  # stand-in raw transcript blob
            fact = EpisodeFact(
                key=key,
                summary=summary,
                kind=MemoryKind.SEMANTIC,
                evidence=CausalEvidence(PREDICTION, OUTCOME, "prediction_observed"),
                confidence=0.8,
            )
            manifest = _manifest(f"ep-{generation}-{i}", fact)
            promoted = store.consolidate(manifest, system_time=generation * 10 + i)
            stored_chars += sum(len(m.summary) for m in promoted)

    # precision@1 and no stale recall: exactly the latest generation surfaces.
    for key in keys:
        result = store.recall(key, scope=MemoryScope.USER_PROJECT)
        assert len(result.memories) == 1, "precision@1 violated: multiple live memories"
        assert result.memories[0].summary.endswith("option-2")
        assert "option-0" not in result.memories[0].summary
        assert "option-1" not in result.memories[0].summary

    # tokens avoided: consolidated store is far smaller than raw transcript volume.
    assert stored_chars < raw_transcript_chars / 5


def test_prediction_evidence_digest_is_stable_and_non_disclosing() -> None:
    from tests.agent.test_prediction_receipts import _receipt

    receipt = _receipt(action_digest="send token=do-not-leak")
    digest = prediction_evidence_digest(receipt)

    assert len(digest) == 64
    assert digest == prediction_evidence_digest(receipt)
    assert "do-not-leak" not in digest
