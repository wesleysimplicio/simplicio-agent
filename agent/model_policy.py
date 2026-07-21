"""Central model safety policy shared by CLI and gateway entry points.

This module does NOT hardcode any model ID — the model comes from config.yaml only.
"""

from __future__ import annotations

from urllib.parse import urlparse

_NVIDIA_PROVIDER_IDS = frozenset({"nvidia", "nvidia-nim", "nvidia_nim", "nvidia nim"})


def is_nvidia_model(
    model: str | None,
    provider: str | None = None,
    base_url: str | None = None,
) -> bool:
    """Return whether a model request targets NVIDIA."""
    model_id = str(model or "").strip().lower()
    provider_id = str(provider or "").strip().lower()
    endpoint = str(base_url or "").strip().lower()
    if model_id.startswith("nvidia/"):
        return True
    if provider_id in _NVIDIA_PROVIDER_IDS:
        return True
    try:
        host = (urlparse(endpoint).hostname or "").lower()
    except ValueError:
        host = ""
    return host == "integrate.api.nvidia.com" or host.endswith(".nvidia.com")


def enforce_model_policy(
    model: str | None,
    provider: str | None = None,
    base_url: str | None = None,
    *,
    default_model: str = "",
) -> str:
    """Replace a temporarily forbidden NVIDIA selection with the default.

    The model is resolved from config.yaml — no model IDs are hardcoded here.
    """
    requested = str(model or "").strip()
    if requested and is_nvidia_model(requested, provider, base_url):
        return default_model
    return requested


def model_policy_error(model: str | None) -> str:
    """Return the user-facing explanation for a rejected model switch."""
    return (
        f"Modelo '{str(model or '').strip()}' bloqueado temporariamente: "
        "modelos NVIDIA estão proibidos nos dois bots. "
        "Configure outro modelo no config.yaml."
    )