"""Tests for agent.distribution — DistributionManifest and Publisher.

Issue #50: distribuição unificada.
"""

from __future__ import annotations

import tempfile
import textwrap
from pathlib import Path

import pytest

from agent.distribution.manifest import DistributionManifest
from agent.distribution.publisher import Publisher


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_toml(content: str) -> Path:
    """Write *content* to a temp pyproject.toml and return its Path."""
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".toml", delete=False, encoding="utf-8"
    )
    tmp.write(textwrap.dedent(content))
    tmp.flush()
    tmp.close()
    return Path(tmp.name)


# ---------------------------------------------------------------------------
# DistributionManifest tests
# ---------------------------------------------------------------------------

class TestDistributionManifest:
    def test_basic_creation(self):
        """DistributionManifest stores all fields correctly."""
        m = DistributionManifest(
            name="simplicio-agent",
            version="0.25.0",
            packages=["simplicio_agent"],
            extras={"dev": ["pytest==8.0.0"]},
            entry_points={"simplicio": "simplicio_agent.__main__:main"},
        )
        assert m.name == "simplicio-agent"
        assert m.version == "0.25.0"
        assert m.packages == ["simplicio_agent"]
        assert m.extras == {"dev": ["pytest==8.0.0"]}
        assert m.entry_points == {"simplicio": "simplicio_agent.__main__:main"}

    def test_defaults_are_empty_collections(self):
        """packages, extras, and entry_points default to empty collections."""
        m = DistributionManifest(name="my-pkg", version="1.0.0")
        assert m.packages == []
        assert m.extras == {}
        assert m.entry_points == {}

    def test_empty_name_raises(self):
        """DistributionManifest rejects an empty name."""
        with pytest.raises(ValueError, match="name"):
            DistributionManifest(name="", version="1.0.0")

    def test_empty_version_raises(self):
        """DistributionManifest rejects an empty version."""
        with pytest.raises(ValueError, match="version"):
            DistributionManifest(name="pkg", version="")


# ---------------------------------------------------------------------------
# Publisher.build_manifest tests
# ---------------------------------------------------------------------------

class TestPublisherBuildManifest:
    def test_build_from_real_pyproject(self, tmp_path):
        """build_manifest parses name, version, scripts from a minimal TOML."""
        toml_content = """\
            [project]
            name = "simplicio-agent"
            version = "0.25.0"

            [project.scripts]
            simplicio = "simplicio_agent.__main__:main"
        """
        p = tmp_path / "pyproject.toml"
        p.write_text(textwrap.dedent(toml_content), encoding="utf-8")

        manifest = Publisher.build_manifest(p)

        assert manifest.name == "simplicio-agent"
        assert manifest.version == "0.25.0"
        assert manifest.entry_points == {"simplicio": "simplicio_agent.__main__:main"}

    def test_build_with_extras(self, tmp_path):
        """build_manifest reads optional-dependencies into extras."""
        toml_content = """\
            [project]
            name = "my-pkg"
            version = "2.0.0"

            [project.optional-dependencies]
            dev = ["pytest==8.0.0", "mypy==1.0.0"]
            docs = ["sphinx==7.0.0"]
        """
        p = tmp_path / "pyproject.toml"
        p.write_text(textwrap.dedent(toml_content), encoding="utf-8")

        manifest = Publisher.build_manifest(p)

        assert "dev" in manifest.extras
        assert "sphinx==7.0.0" in manifest.extras["docs"]

    def test_build_file_not_found(self):
        """build_manifest raises FileNotFoundError for missing paths."""
        with pytest.raises(FileNotFoundError):
            Publisher.build_manifest("/nonexistent/path/pyproject.toml")

    def test_build_fallback_packages(self, tmp_path):
        """build_manifest derives packages from name when not declared."""
        toml_content = """\
            [project]
            name = "my-cool-pkg"
            version = "0.1.0"
        """
        p = tmp_path / "pyproject.toml"
        p.write_text(textwrap.dedent(toml_content), encoding="utf-8")

        manifest = Publisher.build_manifest(p)

        # Fallback: hyphen → underscore
        assert "my_cool_pkg" in manifest.packages


# ---------------------------------------------------------------------------
# Publisher.validate tests
# ---------------------------------------------------------------------------

class TestPublisherValidate:
    def test_valid_manifest_has_no_errors(self):
        """A well-formed manifest produces an empty error list."""
        m = DistributionManifest(
            name="simplicio-agent",
            version="0.25.0",
            packages=["simplicio_agent"],
            entry_points={"simplicio": "simplicio_agent.__main__:main"},
        )
        assert Publisher.validate(m) == []

    def test_empty_packages_is_an_error(self):
        """validate flags manifests with no packages."""
        m = DistributionManifest(name="pkg", version="1.0.0", packages=[])
        errors = Publisher.validate(m)
        assert any("packages" in e for e in errors)

    def test_bad_entry_point_format_is_an_error(self):
        """validate flags entry_points without 'module:callable' format."""
        m = DistributionManifest(
            name="pkg",
            version="1.0.0",
            packages=["pkg"],
            entry_points={"cli": "no_colon_here"},
        )
        errors = Publisher.validate(m)
        assert any("entry_point" in e for e in errors)

    def test_bad_version_prefix_is_an_error(self):
        """validate flags versions that don't start with a digit."""
        m = DistributionManifest(
            name="pkg",
            version="v1.0.0",
            packages=["pkg"],
        )
        errors = Publisher.validate(m)
        assert any("version" in e for e in errors)
