from __future__ import annotations

from pathlib import Path

from scripts import check_native_program

ROOT = Path(__file__).parents[2]
MANIFEST_PATH = ROOT / "docs/architecture/native-program-gate.yaml"
GRAPH_PATH = Path("docs/architecture/native-p0-reconciliation.yaml")


def _manifest() -> dict:
    return check_native_program.load_manifest(MANIFEST_PATH)


def test_parent_manifest_covers_every_native_child_and_graph() -> None:
    assert (
        check_native_program.validate_manifest(
            _manifest(), root=ROOT, graph_path=GRAPH_PATH
        )
        == []
    )


def test_missing_and_duplicate_child_mappings_fail_closed() -> None:
    manifest = _manifest()
    manifest["children"] = manifest["children"][1:]
    errors = check_native_program.validate_manifest(
        manifest, root=ROOT, graph_path=GRAPH_PATH
    )
    assert "missing Native child mapping for #315" in errors

    manifest = _manifest()
    manifest["children"].append(dict(manifest["children"][0]))
    errors = check_native_program.validate_manifest(
        manifest, root=ROOT, graph_path=GRAPH_PATH
    )
    assert "duplicate Native child mapping for #315" in errors


def test_missing_artifact_and_graph_drift_fail_closed() -> None:
    manifest = _manifest()
    manifest["children"][0]["tests"] = ["tests/missing-native-test.py"]
    errors = check_native_program.validate_manifest(
        manifest, root=ROOT, graph_path=GRAPH_PATH
    )
    assert any("path not found" in error for error in errors)

    manifest = _manifest()
    manifest["children"][0]["program_graph_p0"] = [209]
    errors = check_native_program.validate_manifest(
        manifest, root=ROOT, graph_path=GRAPH_PATH
    )
    assert any("program graph coverage diverges" in error for error in errors)


def test_evidence_must_have_explicit_truth_class() -> None:
    manifest = _manifest()
    manifest["evidence"]["rollback"] = "rollback pending"
    errors = check_native_program.validate_manifest(
        manifest, root=ROOT, graph_path=GRAPH_PATH
    )
    assert any("evidence.rollback" in error for error in errors)


def test_unverified_evidence_blocks_completion_but_not_contract() -> None:
    ready, pending = check_native_program.readiness(_manifest())
    assert ready is False
    assert len(pending) == 3


def test_live_check_is_read_only_and_api_mockable() -> None:
    calls: list[int] = []

    def fetch(issue: int) -> dict[str, object]:
        calls.append(issue)
        child = next(item for item in _manifest()["children"] if item["issue"] == issue)
        return {
            "number": issue,
            "title": child["title"],
            "body": "Parent: #314\nADR: ADR-0023",
        }

    assert check_native_program.check_live_issues(_manifest(), fetch) == []
    assert calls == list(range(315, 324))


def test_live_check_marks_api_failure_unverified() -> None:
    errors = check_native_program.check_live_issues(
        _manifest(), lambda issue: (_ for _ in ()).throw(OSError("offline"))
    )
    assert len(errors) == 9
    assert all(error.startswith("UNVERIFIED|") for error in errors)
