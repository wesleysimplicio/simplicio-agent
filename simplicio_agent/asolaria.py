"""Stable checkout-local access to the deterministic Asolaria patterns.

The implementations remain in ``skills/asolaria-patterns/lib`` so the skill
and its existing tests keep their current ownership.  This module is a small
public facade for callers that need the N-Nest and PRISM-COMB contracts from a
source checkout; it does not claim integration with ``simplicio-runtime``.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

__all__ = [
    "addressing_geometry",
    "citizen_identity",
    "encode_addr",
    "fnv1a64",
    "prism_crt_capacity",
    "prism_crt_decompose",
    "prism_crt_recombine",
    "prism_forward",
    "prism_inverse",
    "prism_seal",
    "realmathpos",
    "run_n_nest",
    "selftest",
    "sha16",
    "verify_citizen",
]

_PATTERN_DIR = (
    Path(__file__).resolve().parents[1] / "skills" / "asolaria-patterns" / "lib"
)
_MODULES: dict[str, ModuleType] = {}


def _load_pattern(name: str) -> ModuleType:
    module = _MODULES.get(name)
    if module is not None:
        return module

    path = _PATTERN_DIR / f"{name}.py"
    if not path.is_file():
        raise RuntimeError(
            "Asolaria source-tree facade is not packaged yet: "
            f"missing {path.as_posix()}"
        )

    module_name = f"_simplicio_agent_asolaria_{name}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load deterministic Asolaria module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    _MODULES[name] = module
    return module


def run_n_nest(tamper_addr: str | None = None) -> Any:
    """Build the existing deterministic depth-N nest and return its apex."""

    return _load_pattern("nest_depthn").run_tree(tamper_addr)


def prism_forward(addr: str) -> int:
    """Return the existing PRISM-COMB ground-truth value for ``addr``."""

    return _load_pattern("prism_comb").forward(addr)


def prism_seal(value: int) -> str:
    """Return the existing PRISM-COMB seal for a ground-truth value."""

    return _load_pattern("prism_comb").seal(value)


def prism_inverse(addr: str, reported_seal: str) -> tuple[bool, int]:
    """Verify a seal through the existing PRISM-COMB inverse check."""

    return _load_pattern("prism_comb").inverse(addr, reported_seal)


def prism_crt_capacity() -> int:
    """Return the declared CRT capacity of the existing PRISM-COMB module."""

    return _load_pattern("prism_comb").crt_capacity()


def prism_crt_decompose(value: int) -> tuple[int, ...]:
    """Decompose ``value`` with the existing PRISM-COMB CRT moduli."""

    return _load_pattern("prism_comb").crt_decompose(value)


def prism_crt_recombine(
    residues: tuple[int, ...], domain_size: int | None = None
) -> tuple[str, int | None]:
    """Recombine CRT residues while preserving the existing capacity gate."""

    return _load_pattern("prism_comb").crt_recombine(residues, domain_size=domain_size)


def addressing_geometry() -> ModuleType:
    """Return the Addressing Geometry pattern module (issue #36)."""
    return _load_pattern("addressing_geometry")


def realmathpos(file: str, line: int, col: int) -> Any:
    """REALMATHPOS — file:line:col as a monotone, locality-preserving coord."""
    return _load_pattern("addressing_geometry").realmathpos(file, line, col)


def fnv1a64(data: bytes | str) -> int:
    """FNV-1a/64 fast non-cryptographic hash of a file path."""
    return _load_pattern("addressing_geometry").fnv1a64(data)


def sha16(s: str) -> str:
    """Canonical 16-hex module identifier (sha256[:16])."""
    return _load_pattern("addressing_geometry").sha16(s)


def encode_addr(tier: str, file: str, line: int, col: int) -> int:
    """Locality-preserving slot for ``(file, line, col)`` in ``tier``."""
    return _load_pattern("addressing_geometry").encode_addr(tier, file, line, col)


def citizen_identity(
    file: str, line: int, col: int, tier: str = "1024", tag: str = "CANON"
) -> Any:
    """Fused canonical citizen identity CIT-<file_id>-<tier><slot>[-tag]."""
    return _load_pattern("addressing_geometry").citizen_identity(
        file, line, col, tier=tier, tag=tag  # type: ignore[arg-type]
    )


def verify_citizen(cit: Any, file: str, line: int, col: int) -> bool:
    """Re-derive a citizen identity and close the round-trip (refuses UNVERIFIED)."""
    return _load_pattern("addressing_geometry").verify_citizen(cit, file, line, col)


def selftest() -> int:
    """Run every pattern selftest and return zero on success."""
    _load_pattern("nest_depthn").selftest()
    _load_pattern("prism_comb").selftest()
    _load_pattern("addressing_geometry").selftest()
    return 0


if __name__ == "__main__":
    if "--selftest" not in sys.argv:
        raise SystemExit("usage: python -m simplicio_agent.asolaria --selftest")
    raise SystemExit(selftest())
