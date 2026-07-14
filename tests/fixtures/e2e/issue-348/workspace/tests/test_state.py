from pathlib import Path


def test_issue_348_fixture_change_is_ready() -> None:
    state = Path(__file__).parents[1] / "state.txt"
    assert state.read_text(encoding="utf-8") == "status=ready\nversion=2\n"
