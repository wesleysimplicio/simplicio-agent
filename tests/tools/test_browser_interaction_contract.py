from tools.browser_interaction_contract import (
    browser_interaction_receipt,
    browser_provider_capabilities,
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
