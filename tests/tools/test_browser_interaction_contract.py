from tools.browser_interaction_contract import (
    BrowserStateRegistry,
    browser_interaction_receipt,
    browser_provider_capabilities,
    vision_escalation_reason,
)


def test_browser_provider_capabilities_are_dom_first() -> None:
    caps = browser_provider_capabilities()

    assert caps["routing"]["primary"] == "dom/cdp"
    assert caps["routing"]["fallback"] == "visual"
    assert "DOM/CDP" in caps["routing"]["fallback_reason"]
    assert caps["safety"]["no_effect"] == ["snapshot", "console"]
    assert "navigate" in caps["operations"]


def test_browser_interaction_receipt_marks_read_only_routes() -> None:
    receipt = browser_interaction_receipt(
        surface="computer_use.capture",
        selection="auxiliary.vision",
        fallback_reason="visual fallback required",
    )

    assert receipt == {
        "surface": "computer_use.capture",
        "selection": "auxiliary.vision",
        "effect": "read_only",
        "no_effect": True,
        "fallback_reason": "visual fallback required",
    }


def test_compact_state_persists_redacted_snapshot_and_generation_bound_refs(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_BROWSER_STATE_DIR", str(tmp_path))
    registry = BrowserStateRegistry()

    first = registry.capture(
        "task-1",
        '- button "Send" [ref=e2]\n- textbox "Password" [ref=e1]\nsecret sk-proj-ABCD1234567890EFGH',
        {
            "e2": {"role": "button", "name": "Send"},
            "e1": {"role": "textbox", "name": "Password"},
        },
    )

    assert first["generation"] == 1
    assert first["actions"][0]["id"] == "@g1-e2"
    assert first["snapshot_bytes"] > 0
    persisted = next(tmp_path.glob("*.json")).read_text(encoding="utf-8")
    assert "sk-proj-ABCD1234567890EFGH" not in persisted
    assert first["token_budget"] <= 600

    second = registry.capture("task-1", '- button "Other" [ref=e2]', {"e2": {"role": "button"}})
    assert second["generation"] == 2
    assert registry.resolve("task-1", "@g1-e2")[1] == "stale browser reference; refresh browser_snapshot"
    assert registry.resolve("task-1", "@g2-e2") == ("@e2", None)


def test_vision_escalation_is_bounded_and_evidence_based():
    assert vision_escalation_reason("<canvas id='chart'></canvas>") == "canvas"
    assert vision_escalation_reason("- button 'Send'") is None
    assert vision_escalation_reason("- image-only control") == "image_only_control"
    assert vision_escalation_reason("- heading 'Empty'") == "inaccessible_accessibility"
    assert vision_escalation_reason("- button 'Send'", explicit_request=True) == "explicit_request"
