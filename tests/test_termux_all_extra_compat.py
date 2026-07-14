"""Regression coverage for the Termux broad install profile."""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = REPO_ROOT / "pyproject.toml"
INSTALL_SH = REPO_ROOT / "scripts" / "install.sh"


def test_pyproject_defines_termux_all_without_known_blockers() -> None:
    text = PYPROJECT.read_text()
    assert "termux-all = [" in text
    # Simplicio rebrand renamed the pip package from hermes-agent to
    # simplicio-agent.
    assert '"simplicio-agent[termux]"' in text
    assert '"simplicio-agent[matrix]"' not in text.split("termux-all = [", 1)[1].split("]", 1)[0]
    assert '"simplicio-agent[voice]"' not in text.split("termux-all = [", 1)[1].split("]", 1)[0]


# test_install_script_prefers_termux_all_then_fallbacks was removed: it
# asserted a pip-based install fallback chain ("pip install -e '.[termux-all]'
# ... trying baseline Termux profile ... trying base install") that no longer
# exists. scripts/install.sh was rewritten from a pip/venv installer into a
# prebuilt-binary downloader (see the "Uso" header and BINARY_NAME/DOWNLOAD_BASE
# vars in the current script) and carries no Termux-specific pip fallback
# logic anymore — grep for "termux" in the current install.sh turns up only a
# single unrelated comment. Restoring the old fallback chain would undo that
# rewrite; this is tracked as part of the broader install.sh test-suite gap
# (see the FINAL VERIFY report's install_sh cluster note), not fixed here.
