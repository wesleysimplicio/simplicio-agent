"""DistributionManifest — dataclass for unified distribution metadata.

Covers issue #50: unified distribution (single binary + package managers).
Stdlib only; no external dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class DistributionManifest:
    """Unified distribution manifest for simplicio-agent.

    Attributes:
        name: Package/distribution name (e.g. ``simplicio-agent``).
        version: PEP 440 version string (e.g. ``0.25.0``).
        packages: List of Python package directories included in the distribution.
        extras: Mapping of extras names to their dependency lists.
        entry_points: Mapping of console script names to their Python callables,
            e.g. ``{"simplicio": "simplicio_agent.__main__:main"}``.
    """

    name: str
    version: str
    packages: List[str] = field(default_factory=list)
    extras: Dict[str, List[str]] = field(default_factory=dict)
    entry_points: Dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("DistributionManifest.name must not be empty")
        if not self.version:
            raise ValueError("DistributionManifest.version must not be empty")
