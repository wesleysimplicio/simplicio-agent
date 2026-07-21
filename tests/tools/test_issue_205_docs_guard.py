from pathlib import Path

from tools.issue_205_docs_guard import load_inventory, scan


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_issue_205_inventory_covers_the_entry_documents():
    inventory = load_inventory()

    assert inventory["schema"] == "simplicio.rename-inventory/v1"
    assert inventory["issue"] == 205
    assert set(inventory["scope"]) == {
        "README.md",
        "CONTRIBUTING.md",
        "CONTRIBUTING.es.md",
        "SECURITY.md",
        "SECURITY.es.md",
    }
    assert not scan(REPO_ROOT, inventory)
