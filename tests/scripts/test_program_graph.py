from __future__ import annotations

from pathlib import Path

import yaml

from scripts import check_program_graph


def _manifest() -> dict:
    return check_program_graph.load_manifest(
        Path("docs/architecture/native-p0-reconciliation.yaml")
    )


def test_manifest_has_one_valid_relation_per_p0_issue() -> None:
    assert check_program_graph.validate_manifest(_manifest()) == []


def test_missing_relation_is_rejected() -> None:
    manifest = _manifest()
    manifest["relations"] = manifest["relations"][1:]
    errors = check_program_graph.validate_manifest(manifest)
    assert "missing relation for P0 issue #228" in errors


def test_duplicate_relation_is_rejected() -> None:
    manifest = _manifest()
    manifest["relations"].append(dict(manifest["relations"][0]))
    errors = check_program_graph.validate_manifest(manifest)
    assert "duplicate relation for P0 issue #228" in errors


def test_invalid_relation_and_target_are_rejected() -> None:
    manifest = _manifest()
    manifest["relations"][0]["relation"] = "blocks"
    manifest["relations"][0]["native_targets"] = [999]
    errors = check_program_graph.validate_manifest(manifest)
    assert any("invalid relation" in error for error in errors)
    assert any("invalid native target" in error for error in errors)


def test_unknown_p0_issue_is_rejected() -> None:
    manifest = _manifest()
    manifest["relations"][0]["issue"] = 999
    errors = check_program_graph.validate_manifest(manifest)
    assert any("unknown P0 issue #999" in error for error in errors)
    assert any("missing relation for P0 issue #228" in error for error in errors)


def test_duplicate_yaml_mapping_key_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text("schema_version: 1\nschema_version: 2\n", encoding="utf-8")
    try:
        check_program_graph.load_manifest(path)
    except yaml.constructor.ConstructorError as exc:
        assert "duplicate key" in str(exc)
    else:  # pragma: no cover - assertion makes the failure explicit
        raise AssertionError("duplicate YAML key was silently accepted")


def test_body_snapshot_drift_is_rejected() -> None:
    manifest = _manifest()
    body = Path("docs/architecture/native-p0-epic-314-body.md").read_text(
        encoding="utf-8"
    )
    assert check_program_graph.check_body_snapshot(manifest, body) == []
    assert check_program_graph.check_body_snapshot(
        manifest, body.replace("#319", "#320", 1)
    )


def test_main_passes_checked_in_graph() -> None:
    assert check_program_graph.main([]) == 0
