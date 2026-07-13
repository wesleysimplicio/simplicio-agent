"""Regression test for issue #201: user-facing "Hermes" strings in the web
dashboard must read "Simplicio Agent" instead. Internal identifiers (env var
names, ~/.hermes paths, the X-Hermes-Session-Token header, route/source ids
like "hermes-index") are intentionally left untouched and are not covered
here.
"""

from hermes_cli import web_server


def test_app_title_is_simplicio_agent():
    assert web_server.app.title == "Simplicio Agent"


def test_platform_override_descriptions_have_no_hermes_branding():
    for slug, override in web_server._PLATFORM_OVERRIDES.items():
        description = override.get("description", "")
        assert "Hermes" not in description, (
            f"platform override {slug!r} still says 'Hermes': {description!r}"
        )


def test_dashboard_theme_labels_have_no_hermes_branding():
    for theme in web_server._BUILTIN_DASHBOARD_THEMES:
        for field in ("label", "description"):
            value = theme.get(field, "")
            assert "Hermes" not in value, (
                f"theme {theme.get('name')!r} field {field!r} still says "
                f"'Hermes': {value!r}"
            )


def test_skill_hub_source_label_has_no_hermes_branding():
    assert web_server._SKILL_HUB_SOURCE_LABELS["hermes-index"] == "Simplicio Agent Index"
