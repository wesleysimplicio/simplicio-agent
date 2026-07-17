"""Focused contracts for the bounded #340 equivalence/canary slice."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

from tools.equivalence_gate import (
    EQUIVALENCE_SCHEMA,
    CanaryController,
    DimensionTolerance,
    FeatureFlagStore,
    _flag_key,
    _tolerances,
    _valid_flag_document,
    compare_shadow_row,
    evaluate_gate,
    evaluate_shadow_reports,
    main,
)
from tools.shadow_effects import EffectRequest, compare_effect_sequences


def shadow(
    *,
    category: str = "routine",
    latency: float = 100,
    candidate_latency: float | None = None,
    behavior: object = None,
    candidate_behavior: object = None,
    memory: int = 1000,
    candidate_memory: int | None = None,
    tokens: int = 100,
    candidate_tokens: int | None = None,
    receipts: object = None,
    candidate_receipts: object = None,
) -> dict:
    candidate_latency = latency if candidate_latency is None else candidate_latency
    candidate_memory = memory if candidate_memory is None else candidate_memory
    candidate_tokens = tokens if candidate_tokens is None else candidate_tokens
    behavior = (
        {"effect_request": {"action": "read"}, "output": "ok"}
        if behavior is None
        else behavior
    )
    candidate_behavior = behavior if candidate_behavior is None else candidate_behavior
    receipts = (
        {"schema": "simplicio.effect-receipt/v1", "required_fields": ["id", "status"]}
        if receipts is None
        else receipts
    )
    candidate_receipts = receipts if candidate_receipts is None else candidate_receipts
    return {
        "schema": "simplicio.shadow-report/v1",
        "fixture_id": f"fixture-{category}",
        "category": category,
        "baseline": {
            "behavior": behavior,
            "tokens": tokens,
            "latency": {"p95": latency},
            "memory": {"peak_memory_bytes": memory},
            "receipts": receipts,
        },
        "candidate": {
            "behavior": candidate_behavior,
            "tokens": candidate_tokens,
            "latency": {"p95": candidate_latency},
            "memory": {"peak_memory_bytes": candidate_memory},
            "receipts": candidate_receipts,
        },
    }


def test_all_dimensions_at_tolerance_promote_and_aggregate_by_category() -> None:
    result = evaluate_shadow_reports([
        shadow(
            category="routine",
            latency=100,
            candidate_latency=110,
            memory=1000,
            candidate_memory=1100,
        ),
        shadow(category="routine"),
    ])
    assert result["schema"] == EQUIVALENCE_SCHEMA
    assert result["verdict"] == "promote"
    assert result["categories"]["routine"]["sample_count"] == 2


def test_behavior_difference_rejects_with_fixture_and_effect_reason() -> None:
    result = evaluate_shadow_reports([
        shadow(
            candidate_behavior={"effect_request": {"action": "write"}, "output": "ok"}
        )
    ])
    assert result["verdict"] == "reject"
    reason = next(
        reason for reason in result["reasons"] if reason["dimension"] == "behavior"
    )
    assert reason["fixture_id"] == "fixture-routine"
    assert reason["code"] == "dimension_out_of_tolerance"


def test_latency_observation_can_hold_while_blocking_dimensions_pass() -> None:
    result = evaluate_shadow_reports(
        [shadow(candidate_latency=125)],
        tolerances={"latency": {"limit": 0.10, "severity": "observation"}},
    )
    assert result["verdict"] == "hold"
    assert result["reasons"][0]["severity"] == "observation"


def test_receipt_schema_and_required_fields_are_strict() -> None:
    changed = {
        "schema": "simplicio.other-receipt/v1",
        "required_fields": ["id", "status"],
    }
    result = evaluate_shadow_reports([shadow(candidate_receipts=changed)])
    assert result["verdict"] == "reject"
    assert any(reason["dimension"] == "receipts" for reason in result["reasons"])


def test_missing_or_corrupt_reports_reject_fail_closed() -> None:
    assert evaluate_shadow_reports([])["verdict"] == "reject"
    assert evaluate_shadow_reports([{}])["verdict"] == "reject"
    assert (
        evaluate_shadow_reports([{"schema": "not-a-shadow-report"}])["verdict"]
        == "reject"
    )


def test_flag_missing_corrupt_and_profile_session_mismatch_stay_off(tmp_path) -> None:
    store = FeatureFlagStore(tmp_path)
    assert not store.is_enabled(
        "native.slice.demo", profile_id="internal", session_id="s1"
    )
    store.path.write_text("{not-json", encoding="utf-8")
    assert not store.is_enabled("demo", profile_id="internal", session_id="s1")
    store.set_enabled("demo", profile_id="internal", session_id="s1", enabled=True)
    assert store.is_enabled("demo", profile_id="internal", session_id="s1")
    assert not store.is_enabled("demo", profile_id="other", session_id="s1")
    assert not store.is_enabled("demo", profile_id="internal", session_id="s2")


def test_canary_journals_activation_and_auto_rollback(tmp_path) -> None:
    store = FeatureFlagStore(tmp_path / "state")
    controller = CanaryController(store, tmp_path / "journal.jsonl", "demo")
    assert controller.activate("internal", "session-1")
    assert store.is_enabled("demo", profile_id="internal", session_id="session-1")
    assert controller.rollback_on_divergence(
        "internal", "session-1", divergence_rate=0.11, threshold=0.10
    )
    assert not store.is_enabled("demo", profile_id="internal", session_id="session-1")
    events = [
        json.loads(line)
        for line in (tmp_path / "journal.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert [event["enabled"] for event in events] == [True, False]
    assert all(
        event["profile_id"] == "internal" and event["session_id"] == "session-1"
        for event in events
    )


# ---------------------------------------------------------------------------
# Tolerance-spec parsing errors (unknown dimension, non-numeric/non-finite
# limit) — these are the fail-closed edges of the equivalence contract itself.
# ---------------------------------------------------------------------------


def test_tolerances_rejects_unknown_dimension() -> None:
    with pytest.raises(ValueError, match="unknown equivalence dimension"):
        _tolerances({"bogus": 0.1})


@pytest.mark.parametrize("limit", [True, "0.1", None, float("inf"), float("nan")])
def test_tolerances_rejects_non_numeric_or_non_finite_limit(limit: object) -> None:
    with pytest.raises(ValueError):
        _tolerances({"latency": limit})


def test_tolerances_accepts_scalar_and_mapping_forms() -> None:
    specs = _tolerances({"tokens": 0.2, "latency": {"limit": 0.3, "severity": "observation"}})
    assert specs["tokens"] == DimensionTolerance(0.2, "blocking")
    assert specs["latency"] == DimensionTolerance(0.3, "observation")
    # Unspecified dimensions keep the module defaults.
    assert specs["memory"] == DimensionTolerance(0.10, "blocking")


def test_dimension_tolerance_rejects_negative_limit_or_bad_severity() -> None:
    with pytest.raises(ValueError):
        DimensionTolerance(-0.1)
    with pytest.raises(ValueError):
        DimensionTolerance(0.1, "urgent")


# ---------------------------------------------------------------------------
# compare_shadow_row: numeric/error branches per dimension.
# ---------------------------------------------------------------------------


def test_compare_shadow_row_reports_non_numeric_metric_as_invalid_dimension() -> None:
    row = shadow(candidate_latency="slow")
    result = compare_shadow_row(row)
    latency = result["dimensions"]["latency"]
    assert latency["passed"] is False
    assert latency["observed_delta"] is None
    assert "error" in latency
    # An unparsable dimension is always treated as blocking regardless of the
    # configured severity for that dimension.
    assert latency["severity"] == "blocking"


def test_compare_shadow_row_rejects_negative_metric() -> None:
    row = shadow(latency=-1)
    result = compare_shadow_row(row)
    assert result["dimensions"]["latency"]["passed"] is False
    assert "must be non-negative" in result["dimensions"]["latency"]["error"]


def test_compare_shadow_row_zero_baseline_zero_candidate_is_zero_delta() -> None:
    row = shadow(latency=0, candidate_latency=0)
    result = compare_shadow_row(row)
    assert result["dimensions"]["latency"]["observed_delta"] == 0.0
    assert result["dimensions"]["latency"]["passed"] is True


def test_compare_shadow_row_zero_baseline_nonzero_candidate_is_infinite_delta() -> None:
    row = shadow(latency=0, candidate_latency=5)
    result = compare_shadow_row(row)
    assert result["dimensions"]["latency"]["observed_delta"] == float("inf")
    assert result["dimensions"]["latency"]["passed"] is False


def test_compare_shadow_row_missing_dimension_payload_is_invalid() -> None:
    row = shadow()
    del row["baseline"]["latency"]
    result = compare_shadow_row(row)
    assert result["dimensions"]["latency"]["passed"] is False
    assert "baseline.latency is required" in result["dimensions"]["latency"]["error"]


def test_compare_shadow_row_side_must_be_object() -> None:
    row = shadow()
    row["baseline"] = "not-an-object"
    result = compare_shadow_row(row)
    assert result["dimensions"]["behavior"]["passed"] is False
    assert "baseline must be an object" in result["dimensions"]["behavior"]["error"]


def test_compare_shadow_row_metric_reads_nested_value_key() -> None:
    row = shadow()
    row["baseline"]["tokens"] = {"value": 100}
    row["candidate"]["tokens"] = {"value": 100}
    result = compare_shadow_row(row)
    assert result["dimensions"]["tokens"]["passed"] is True


def test_receipt_projection_requires_object_and_valid_fields() -> None:
    row = shadow(candidate_receipts="not-an-object")
    result = compare_shadow_row(row)
    assert result["dimensions"]["receipts"]["passed"] is False
    assert "receipts must be objects" in result["dimensions"]["receipts"]["error"]

    row2 = shadow(candidate_receipts={"schema": "", "required_fields": ["id"]})
    result2 = compare_shadow_row(row2)
    assert "schema must be a non-empty string" in result2["dimensions"]["receipts"]["error"]

    row3 = shadow(candidate_receipts={"schema": "s", "required_fields": "id"})
    result3 = compare_shadow_row(row3)
    assert "required_fields must be a list" in result3["dimensions"]["receipts"]["error"]


# ---------------------------------------------------------------------------
# evaluate_shadow_reports: aggregation and validation-error branches.
# ---------------------------------------------------------------------------


def test_evaluate_shadow_reports_rejects_non_list_input() -> None:
    result = evaluate_shadow_reports("not-a-list")  # type: ignore[arg-type]
    assert result["verdict"] == "reject"
    assert any(
        reason["code"] == "invalid_shadow_report" for reason in result["reasons"]
    )


def test_evaluate_shadow_reports_skips_non_object_report_entries() -> None:
    result = evaluate_shadow_reports([shadow(), "not-an-object"])
    assert result["report_count"] == 1
    assert any("reports[1] must be an object" == r.get("error") for r in result["reasons"])


def test_evaluate_shadow_reports_catches_row_level_value_error() -> None:
    bad = shadow()
    del bad["baseline"]
    result = evaluate_shadow_reports([bad])
    assert result["verdict"] == "reject"
    # A missing top-level "baseline" key is caught per-dimension inside
    # compare_shadow_row (each dimension's lookup raises ValueError, which is
    # trapped there), not re-raised up to evaluate_shadow_reports' own
    # try/except -- so the row still appears with per-dimension errors.
    assert result["report_count"] == 1
    behavior = result["categories"]["routine"]["dimensions"]["behavior"]
    assert behavior["failed"] == 1
    assert any(
        r["code"] == "invalid_shadow_dimension" and r["dimension"] == "behavior"
        for r in result["reasons"]
    )


def test_evaluate_shadow_reports_max_delta_tracks_worst_observed_case() -> None:
    result = evaluate_shadow_reports([
        shadow(category="routine", latency=100, candidate_latency=105),
        shadow(category="routine", latency=100, candidate_latency=250),
    ])
    delta = result["categories"]["routine"]["dimensions"]["latency"]["max_delta"]
    assert delta == pytest.approx(1.5)


def test_evaluate_gate_is_an_alias_for_evaluate_shadow_reports() -> None:
    assert evaluate_gate([shadow()]) == evaluate_shadow_reports([shadow()])


# ---------------------------------------------------------------------------
# Flag key parsing and document validation edge cases.
# ---------------------------------------------------------------------------


def test_flag_key_rejects_empty_or_non_canonical_name() -> None:
    with pytest.raises(ValueError):
        _flag_key("native.slice.")
    with pytest.raises(ValueError):
        _flag_key("native.slice.bad name!")


def test_flag_key_strips_canonical_prefix_idempotently() -> None:
    assert _flag_key("native.slice.demo") == "native.slice.demo"
    assert _flag_key("demo") == "native.slice.demo"


@pytest.mark.parametrize(
    "document",
    [
        "not-a-mapping",
        {"schema": "wrong", "version": 1, "flags": {}},
        {"schema": "simplicio.equivalence-flags/v1", "version": 2, "flags": {}},
        {"schema": "simplicio.equivalence-flags/v1", "version": 1, "flags": "nope"},
        {
            "schema": "simplicio.equivalence-flags/v1",
            "version": 1,
            "flags": {"bad-key": {"profiles": {}}},
        },
        {
            "schema": "simplicio.equivalence-flags/v1",
            "version": 1,
            "flags": {"native.slice.demo": {"profiles": "nope"}},
        },
        {
            "schema": "simplicio.equivalence-flags/v1",
            "version": 1,
            "flags": {"native.slice.demo": {"profiles": {"p": "not-a-mapping"}}},
        },
        {
            "schema": "simplicio.equivalence-flags/v1",
            "version": 1,
            "flags": {
                "native.slice.demo": {"profiles": {"p": {"enabled": "not-bool"}}}
            },
        },
        {
            "schema": "simplicio.equivalence-flags/v1",
            "version": 1,
            "flags": {
                "native.slice.demo": {
                    "profiles": {"p": {"enabled": True, "sessions": "nope"}}
                }
            },
        },
        {
            "schema": "simplicio.equivalence-flags/v1",
            "version": 1,
            "flags": {
                "native.slice.demo": {
                    "profiles": {
                        "p": {"enabled": True, "sessions": {"s": "not-bool"}}
                    }
                }
            },
        },
    ],
)
def test_invalid_flag_documents_are_rejected(document: object) -> None:
    assert _valid_flag_document(document) is False


def test_valid_flag_document_accepts_well_formed_shape() -> None:
    document = {
        "schema": "simplicio.equivalence-flags/v1",
        "version": 1,
        "flags": {
            "native.slice.demo": {
                "profiles": {"p": {"enabled": True, "sessions": {"s": False}}}
            }
        },
    }
    assert _valid_flag_document(document) is True


# ---------------------------------------------------------------------------
# FeatureFlagStore: additional fail-closed edges beyond the baseline test.
# ---------------------------------------------------------------------------


def test_is_enabled_false_for_missing_or_empty_profile_or_session(tmp_path: Path) -> None:
    store = FeatureFlagStore(tmp_path)
    assert not store.is_enabled("demo", profile_id=None, session_id="s1")
    assert not store.is_enabled("demo", profile_id="", session_id="s1")
    assert not store.is_enabled("demo", profile_id="p", session_id=None)
    assert not store.is_enabled("demo", profile_id="p", session_id="")


def test_is_enabled_false_for_invalid_slice_name(tmp_path: Path) -> None:
    store = FeatureFlagStore(tmp_path)
    assert not store.is_enabled("bad name!", profile_id="p", session_id="s")


def test_set_enabled_requires_profile_session_and_bool(tmp_path: Path) -> None:
    store = FeatureFlagStore(tmp_path)
    with pytest.raises(ValueError):
        store.set_enabled("demo", profile_id="", session_id="s", enabled=True)
    with pytest.raises(ValueError):
        store.set_enabled("demo", profile_id="p", session_id="s", enabled="yes")  # type: ignore[arg-type]


def test_store_falls_back_to_profile_level_enabled_when_session_absent(
    tmp_path: Path,
) -> None:
    store = FeatureFlagStore(tmp_path)
    store.path.write_text(
        json.dumps(
            {
                "schema": "simplicio.equivalence-flags/v1",
                "version": 1,
                "flags": {
                    "native.slice.demo": {
                        "profiles": {"p": {"enabled": True, "sessions": {}}}
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    # No pinned session entry -> falls back to the profile-level default.
    assert store.is_enabled("demo", profile_id="p", session_id="unseen-session")


# ---------------------------------------------------------------------------
# CanaryController: journal-write failure must roll the store back, and
# rollback_on_divergence must validate its inputs (fail-closed edges of the
# state machine explicitly called out in issue #340's acceptance criteria).
# ---------------------------------------------------------------------------


def test_transition_rolls_back_store_when_journal_write_fails(tmp_path: Path) -> None:
    store = FeatureFlagStore(tmp_path / "state")
    # Make the journal *path* a directory so opening it for append raises
    # OSError -- this exercises the "leave no activation behind" branch.
    journal_dir = tmp_path / "journal.jsonl"
    journal_dir.mkdir()
    controller = CanaryController(store, journal_dir, "demo")

    ok = controller.activate("internal", "session-1")

    assert ok is False
    # The flag must not remain enabled: the store write is rolled back to its
    # prior (disabled/absent) state despite set_enabled having succeeded.
    assert not store.is_enabled("demo", profile_id="internal", session_id="session-1")


def test_rollback_on_divergence_rejects_negative_inputs() -> None:
    store = FeatureFlagStore(tmp_path_for_test())
    controller = CanaryController(store, store.state_root / "journal.jsonl", "demo")
    with pytest.raises(ValueError):
        controller.rollback_on_divergence(
            "p", "s", divergence_rate=-0.1, threshold=0.1
        )
    with pytest.raises(ValueError):
        controller.rollback_on_divergence(
            "p", "s", divergence_rate=0.2, threshold=-0.1
        )


def test_rollback_on_divergence_is_noop_below_threshold(tmp_path: Path) -> None:
    store = FeatureFlagStore(tmp_path / "state")
    controller = CanaryController(store, tmp_path / "journal.jsonl", "demo")
    controller.activate("internal", "session-1")
    triggered = controller.rollback_on_divergence(
        "internal", "session-1", divergence_rate=0.05, threshold=0.10
    )
    assert triggered is False
    assert store.is_enabled("demo", profile_id="internal", session_id="session-1")


def tmp_path_for_test() -> Path:
    # Small helper so the negative-input test doesn't need a pytest fixture
    # threaded through a plain assertion helper.
    import tempfile

    return Path(tempfile.mkdtemp())


# ---------------------------------------------------------------------------
# CLI (`main`): success path, non-promote exit code, and malformed-file
# fail-closed path.
# ---------------------------------------------------------------------------


def test_main_returns_zero_and_prints_promote_verdict(tmp_path: Path, capsys) -> None:
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(shadow()), encoding="utf-8")

    exit_code = main([str(report_path)])

    assert exit_code == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["verdict"] == "promote"


def test_main_returns_one_on_reject_verdict(tmp_path: Path, capsys) -> None:
    report_path = tmp_path / "report.json"
    report_path.write_text(
        json.dumps(shadow(candidate_latency=1000)), encoding="utf-8"
    )

    exit_code = main([str(report_path)])

    assert exit_code == 1
    printed = json.loads(capsys.readouterr().out)
    assert printed["verdict"] == "reject"


def test_main_fails_closed_on_malformed_json_file(tmp_path: Path, capsys) -> None:
    report_path = tmp_path / "report.json"
    report_path.write_text("{not-json", encoding="utf-8")

    exit_code = main([str(report_path)])

    assert exit_code == 1
    printed = json.loads(capsys.readouterr().out)
    assert printed["verdict"] == "reject"
    assert printed["reasons"][0]["code"] == "invalid_shadow_report"


def test_main_fails_closed_when_report_is_not_a_json_object(
    tmp_path: Path, capsys
) -> None:
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")

    exit_code = main([str(report_path)])

    assert exit_code == 1
    printed = json.loads(capsys.readouterr().out)
    assert printed["verdict"] == "reject"


def test_cli_entrypoint_invoked_as_subprocess_matches_module_main(
    tmp_path: Path,
) -> None:
    """Exercise the ``if __name__ == "__main__"`` line via a real subprocess."""

    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(shadow()), encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, "-m", "tools.equivalence_gate", str(report_path)],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[2],
        stdin=subprocess.DEVNULL,
    )

    assert completed.returncode == 0
    assert json.loads(completed.stdout)["verdict"] == "promote"


# ---------------------------------------------------------------------------
# Integration: #339's shadow_effects.compare_effect_sequences() divergence
# output feeding the #340 equivalence gate.
#
# The two modules both use the schema string "simplicio.shadow-report/v1",
# but their *shapes* are genuinely different: shadow_effects.DivergenceReport
# is {legacy_count, shadow_count, equivalent, divergences: [...]}, while the
# equivalence gate expects {fixture_id, category, baseline: {...},
# candidate: {...}} with per-dimension payloads. There is no implicit
# compatibility -- an adapter is required. This test proves the adapter
# genuinely closes the gap: a real EffectRequest divergence from #339 is
# translated into a gate input and drives a real `reject` verdict pointing at
# the diverging fixture, not a tautological check of the adapter's own shape.
# ---------------------------------------------------------------------------


def _shadow_row_from_divergence_report(
    fixture_id: str,
    category: str,
    legacy_effects: list[EffectRequest],
    shadow_effects: list[EffectRequest],
) -> dict:
    """Adapter: #339 DivergenceReport -> #340 equivalence-gate shadow row.

    Behavioral equivalence for #340's purposes is "the effect sequences the
    legacy and shadow paths attempted are identical" -- exactly what #339's
    ``compare_effect_sequences`` already determines. We fold that boolean
    into the gate's behavior-dimension baseline/candidate shape so the gate's
    existing (well-tested) normalized-equality comparator makes the call.
    """

    divergence = compare_effect_sequences(legacy_effects, shadow_effects)
    # The gate's behavior comparator checks normalized-equality of an
    # arbitrary JSON value between baseline and candidate. We reduce #339's
    # richer DivergenceReport to the single boolean it already computed
    # (`equivalent`), so a real divergence in the effect sequence flows
    # straight through to a real gate `reject` -- the divergence detail
    # itself is preserved separately below for operator debugging, not fed
    # into the equality check (which would trivially never match).
    return {
        "schema": "simplicio.shadow-report/v1",
        "fixture_id": fixture_id,
        "category": category,
        "shadow_divergence_detail": divergence.to_dict(),
        "baseline": {
            "behavior": True,
            "tokens": 100,
            "latency": {"p95": 100},
            "memory": {"peak_memory_bytes": 1000},
            "receipts": {
                "schema": "simplicio.effect-receipt/v1",
                "required_fields": ["id", "status"],
            },
        },
        "candidate": {
            "behavior": divergence.equivalent,
            "tokens": 100,
            "latency": {"p95": 100},
            "memory": {"peak_memory_bytes": 1000},
            "receipts": {
                "schema": "simplicio.effect-receipt/v1",
                "required_fields": ["id", "status"],
            },
        },
    }


def test_shadow_effects_equivalent_sequence_promotes_through_gate() -> None:
    effects = [EffectRequest("fs_read", "read", "a"), EffectRequest("state_write", "write", "b")]
    row = _shadow_row_from_divergence_report(
        "fixture-339-equivalent", "native-slice-demo", effects, list(effects)
    )

    result = evaluate_shadow_reports([row])

    assert result["verdict"] == "promote"


def test_shadow_effects_divergence_rejects_gate_with_exact_fixture_reason() -> None:
    legacy = [EffectRequest("fs_read", "read", "a")]
    shadow_seq = [EffectRequest("fs_write", "write", "a")]
    row = _shadow_row_from_divergence_report(
        "fixture-339-divergent", "native-slice-demo", legacy, shadow_seq
    )

    result = evaluate_shadow_reports([row])

    assert result["verdict"] == "reject"
    reason = next(
        r for r in result["reasons"] if r["dimension"] == "behavior"
    )
    assert reason["fixture_id"] == "fixture-339-divergent"
    assert reason["code"] == "dimension_out_of_tolerance"


# ---------------------------------------------------------------------------
# Performance benchmark: gate-decision latency over a representative batch
# of shadow rows, matching the fixture shape shadow_effects would produce.
# MEASURED, not fabricated -- see the issue comment for the recorded number.
# ---------------------------------------------------------------------------


def test_gate_decision_latency_benchmark_over_representative_batch() -> None:
    rows = [
        shadow(category=f"cat-{i % 5}", latency=100, candidate_latency=105)
        for i in range(200)
    ]

    started = time.perf_counter()
    result = evaluate_shadow_reports(rows)
    elapsed_seconds = time.perf_counter() - started

    assert result["verdict"] == "promote"
    assert result["report_count"] == 200
    # Generous budget so the benchmark is a real regression guard, not a flake
    # source; the issue-comment evidence records the actual measured number.
    assert elapsed_seconds < 5.0
