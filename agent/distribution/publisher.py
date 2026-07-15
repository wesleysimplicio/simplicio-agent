"""Publisher — builds and validates a DistributionManifest from pyproject.toml.

Stdlib only; uses tomllib (Python 3.11+) — no external dependencies.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Dict, List

from .manifest import DistributionManifest


class Publisher:
    """Builds and validates distribution manifests for simplicio-agent."""

    # Required fields that must be present (and non-empty) in the manifest.
    _REQUIRED_FIELDS = ("name", "version")

    @staticmethod
    def build_manifest(pyproject_toml_path: str | Path) -> DistributionManifest:
        """Parse *pyproject.toml* and return a :class:`DistributionManifest`.

        Args:
            pyproject_toml_path: Filesystem path to the ``pyproject.toml`` file.

        Returns:
            A populated :class:`DistributionManifest`.

        Raises:
            FileNotFoundError: If the file does not exist.
            ValueError: If required fields are missing.
            tomllib.TOMLDecodeError: If the file is not valid TOML.
        """
        path = Path(pyproject_toml_path)
        if not path.exists():
            raise FileNotFoundError(f"pyproject.toml not found: {path}")

        with path.open("rb") as fh:
            data = tomllib.load(fh)

        project = data.get("project", {})

        name: str = project.get("name", "")
        version: str = project.get("version", "")

        if not name:
            raise ValueError("pyproject.toml [project].name is missing or empty")
        if not version:
            raise ValueError("pyproject.toml [project].version is missing or empty")

        # Packages — derive from [tool.setuptools.packages.find] or heuristic.
        packages: List[str] = []
        tool_ss = data.get("tool", {}).get("setuptools", {})
        packages_cfg = tool_ss.get("packages", {})
        if isinstance(packages_cfg, dict):
            # packages.find = { where = ["."], include = [...], ... }
            find_cfg = packages_cfg.get("find", {})
            include = find_cfg.get("include", [])
            packages = list(include)
        elif isinstance(packages_cfg, list):
            packages = list(packages_cfg)

        if not packages:
            # Fall back: use the distribution name (replace hyphens → underscores)
            packages = [name.replace("-", "_")]

        # Extras — optional-dependencies table
        raw_extras = project.get("optional-dependencies", {})
        extras: Dict[str, List[str]] = {k: list(v) for k, v in raw_extras.items()}

        # Entry points — scripts table (PEP 621 [project.scripts])
        raw_scripts = project.get("scripts", {})
        entry_points: Dict[str, str] = dict(raw_scripts)

        return DistributionManifest(
            name=name,
            version=version,
            packages=packages,
            extras=extras,
            entry_points=entry_points,
        )

    @staticmethod
    def validate(manifest: DistributionManifest) -> List[str]:
        """Validate a :class:`DistributionManifest` and return a list of error strings.

        An empty list means the manifest is valid.

        Args:
            manifest: The manifest to validate.

        Returns:
            A (possibly empty) list of human-readable error descriptions.
        """
        errors: List[str] = []

        if not manifest.name:
            errors.append("name is empty")

        if not manifest.version:
            errors.append("version is empty")
        else:
            # Basic PEP 440 sanity: must start with a digit.
            if not manifest.version[0].isdigit():
                errors.append(
                    f"version '{manifest.version}' does not look like a PEP 440 version"
                )

        if not manifest.packages:
            errors.append("packages list is empty — nothing would be distributed")

        for script_name, callable_ref in manifest.entry_points.items():
            if ":" not in callable_ref:
                errors.append(
                    f"entry_point '{script_name}' value '{callable_ref}' must be "
                    "'module:callable' format"
                )

        return errors
