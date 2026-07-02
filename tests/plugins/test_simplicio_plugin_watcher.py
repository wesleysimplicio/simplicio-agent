"""Tests for the Watcher PID pattern in plugins/simplicio (issue #17 P0 #1).

`_on_transform_terminal_output` independently re-verifies every
`simplicio edit`/`dev-cli` terminal command by running `simplicio validate`
itself and appending the real result to the terminal output the model
reads. Never fakes a pass when the binary is missing.
"""

from unittest.mock import patch

from plugins.simplicio import (
    _EDIT_CMD_RE,
    _VALIDATE_CMD_RE,
    _on_transform_terminal_output,
    _repo_from_command,
    _run_watcher_validate,
)


REPO = "/Users/wesleysimplicio/Projetos/ai/simplicio-runtime"


def test_edit_and_validate_command_regexes():
    assert _EDIT_CMD_RE.search("simplicio edit --plan '{}' --repo x")
    assert _EDIT_CMD_RE.search('simplicio dev-cli "fix the bug" --repo x')
    assert not _EDIT_CMD_RE.search("simplicio validate --repo x")
    assert not _EDIT_CMD_RE.search("echo not-simplicio edit")  # word-boundary guard
    assert _VALIDATE_CMD_RE.search("simplicio validate --repo x")
    assert not _VALIDATE_CMD_RE.search("simplicio edit --repo x")


def test_repo_from_command_uses_repo_flag():
    repo = _repo_from_command(f"simplicio edit --plan '{{}}' --repo {REPO}")
    # _repo_for_path resolves to the canonical managed root (see
    # plugins/simplicio's own _managed_repo_roots/_repo_for_path), not
    # necessarily byte-identical to the input path -- same contract the
    # existing pre_tool_call tests assert against (name match, not
    # exact-path match).
    assert repo is not None
    assert repo.name == "simplicio-runtime"


def test_repo_from_command_none_for_unmanaged_repo_flag():
    repo = _repo_from_command("simplicio edit --plan '{}' --repo /tmp/some-other-repo")
    assert repo is None


def test_transform_ignores_non_edit_commands():
    assert _on_transform_terminal_output(command="ls -la", output="a.py\n") is None


def test_transform_ignores_validate_commands_to_avoid_recursion():
    assert _on_transform_terminal_output(
        command=f"simplicio validate --repo {REPO}", output="ok"
    ) is None


def test_transform_ignores_edit_commands_outside_managed_repo():
    assert _on_transform_terminal_output(
        command="simplicio edit --plan '{}' --repo /tmp/unmanaged", output="ok"
    ) is None


def test_transform_appends_watcher_note_for_managed_repo_edit():
    with patch("plugins.simplicio._run_watcher_validate", return_value="[watcher] independent verification: PASS"):
        result = _on_transform_terminal_output(
            command=f"simplicio edit --plan '{{}}' --repo {REPO}",
            output="edit applied",
        )
    assert result is not None
    assert result.startswith("edit applied")
    assert "[watcher] independent verification: PASS" in result


def test_transform_disabled_via_env(monkeypatch):
    monkeypatch.setenv("SIMPLICIO_PLUGIN_DISABLE", "1")
    result = _on_transform_terminal_output(
        command=f"simplicio edit --plan '{{}}' --repo {REPO}",
        output="edit applied",
    )
    assert result is None


def test_run_watcher_validate_honest_when_binary_missing():
    with patch("shutil.which", return_value=None):
        note = _run_watcher_validate(REPO)
    assert "[watcher]" in note
    assert "not found on PATH" in note
    assert "could NOT independently verify" in note


def test_run_watcher_validate_reports_pass():
    fake_proc = type("P", (), {"returncode": 0, "stdout": "all green\n", "stderr": ""})()
    with patch("shutil.which", return_value="/usr/local/bin/simplicio"), \
         patch("subprocess.run", return_value=fake_proc):
        note = _run_watcher_validate(REPO)
    assert "[watcher]" in note
    assert "PASS" in note
    assert "all green" in note


def test_run_watcher_validate_reports_fail():
    fake_proc = type("P", (), {"returncode": 1, "stdout": "", "stderr": "3 checks failed\n"})()
    with patch("shutil.which", return_value="/usr/local/bin/simplicio"), \
         patch("subprocess.run", return_value=fake_proc):
        note = _run_watcher_validate(REPO)
    assert "FAIL" in note
    assert "3 checks failed" in note


def test_run_watcher_validate_never_raises_on_subprocess_error():
    with patch("shutil.which", return_value="/usr/local/bin/simplicio"), \
         patch("subprocess.run", side_effect=OSError("boom")):
        note = _run_watcher_validate(REPO)
    assert "[watcher]" in note
    assert "failed to run" in note
