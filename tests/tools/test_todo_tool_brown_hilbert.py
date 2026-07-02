"""Brown-Hilbert `port.port.port` addressing for the todo task orchestrator
(issue #17 P0 #2).

Purely computed from the existing dotted-id convention: TODO_SCHEMA is
untouched (no added tokens on the per-API-call schema), and a flat/
non-dotted todo list behaves exactly as before (address == "R.<id>",
zero hierarchy violations).
"""

import json

from tools.todo_tool import TODO_SCHEMA, TodoStore, todo_tool


class TestAddressOf:
    def test_root_level_id(self):
        assert TodoStore.address_of("0") == "R.0"

    def test_free_form_id(self):
        assert TodoStore.address_of("task-a") == "R.task-a"

    def test_nested_id(self):
        assert TodoStore.address_of("0.1.0") == "R.0.1.0"


class TestParentIdOf:
    def test_root_level_has_no_parent(self):
        assert TodoStore.parent_id_of("0") is None
        assert TodoStore.parent_id_of("task-a") is None

    def test_subtask_parent(self):
        assert TodoStore.parent_id_of("0.1") == "0"

    def test_nested_subtask_parent(self):
        assert TodoStore.parent_id_of("0.1.2") == "0.1"


class TestHierarchyGate:
    def test_flat_list_has_no_violations(self):
        store = TodoStore()
        store.write([
            {"id": "0", "content": "root task", "status": "pending"},
            {"id": "1", "content": "another root task", "status": "in_progress"},
        ])
        assert store.check_hierarchy_gate() == []

    def test_consistent_hierarchy_has_no_violations(self):
        store = TodoStore()
        store.write([
            {"id": "0", "content": "root", "status": "in_progress"},
            {"id": "0.1", "content": "subtask", "status": "in_progress"},
            {"id": "0.1.0", "content": "nested subtask", "status": "completed"},
        ])
        assert store.check_hierarchy_gate() == []

    def test_orphaned_subtask_flagged(self):
        store = TodoStore()
        store.write([
            {"id": "0.1", "content": "subtask with no parent in list", "status": "pending"},
        ])
        violations = store.check_hierarchy_gate()
        assert len(violations) == 1
        assert "orphaned subtask" in violations[0]
        assert "'R.0.1'" in violations[0]
        assert "'R.0'" in violations[0]

    def test_subtask_ahead_of_pending_parent_flagged(self):
        store = TodoStore()
        store.write([
            {"id": "0", "content": "root", "status": "pending"},
            {"id": "0.1", "content": "subtask", "status": "in_progress"},
        ])
        violations = store.check_hierarchy_gate()
        assert len(violations) == 1
        assert "'R.0.1'" in violations[0]
        assert "'in_progress'" in violations[0]
        assert "'R.0'" in violations[0]
        assert "'pending'" in violations[0]

    def test_completed_subtask_of_pending_parent_also_flagged(self):
        store = TodoStore()
        store.write([
            {"id": "0", "content": "root", "status": "pending"},
            {"id": "0.1", "content": "subtask", "status": "completed"},
        ])
        violations = store.check_hierarchy_gate()
        assert len(violations) == 1

    def test_pending_subtask_of_pending_parent_is_fine(self):
        """A subtask that hasn't started yet respects a parent that also
        hasn't started -- only in_progress/completed ahead of a pending
        parent is a violation."""
        store = TodoStore()
        store.write([
            {"id": "0", "content": "root", "status": "pending"},
            {"id": "0.1", "content": "subtask", "status": "pending"},
        ])
        assert store.check_hierarchy_gate() == []


class TestTodoToolOutputIncludesAddressing:
    def test_flat_todos_get_root_addresses_and_no_violations(self):
        result = json.loads(todo_tool(
            todos=[{"id": "1", "content": "task", "status": "pending"}],
            store=TodoStore(),
        ))
        assert result["todos"][0]["address"] == "R.1"
        assert result["summary"]["hierarchy_violations"] == []

    def test_hierarchical_todos_get_dotted_addresses(self):
        store = TodoStore()
        result = json.loads(todo_tool(
            todos=[
                {"id": "0", "content": "root", "status": "in_progress"},
                {"id": "0.1", "content": "subtask", "status": "pending"},
            ],
            store=store,
        ))
        addresses = {item["id"]: item["address"] for item in result["todos"]}
        assert addresses == {"0": "R.0", "0.1": "R.0.1"}

    def test_violation_surfaces_in_tool_result(self):
        result = json.loads(todo_tool(
            todos=[
                {"id": "0", "content": "root", "status": "pending"},
                {"id": "0.1", "content": "subtask", "status": "in_progress"},
            ],
            store=TodoStore(),
        ))
        assert len(result["summary"]["hierarchy_violations"]) == 1

    def test_read_only_call_also_reports_addressing(self):
        store = TodoStore()
        store.write([{"id": "0.1", "content": "orphan", "status": "pending"}])
        result = json.loads(todo_tool(store=store))  # no todos param -> read
        assert result["todos"][0]["address"] == "R.0.1"
        assert len(result["summary"]["hierarchy_violations"]) == 1


def test_schema_unchanged_by_addressing_feature():
    """The addressing feature must add ZERO tokens to the tool schema sent
    on every API call -- it only affects this tool's own result payload.
    id/content/status stay the only declared item properties."""
    props = TODO_SCHEMA["parameters"]["properties"]["todos"]["items"]["properties"]
    assert set(props.keys()) == {"id", "content", "status"}
