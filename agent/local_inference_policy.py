"""Fail-closed pause policy for on-device inference (issue #514)."""

from __future__ import annotations

import os
import ipaddress
from urllib.parse import urlparse


LOCAL_INFERENCE_PAUSED = "LOCAL_INFERENCE_PAUSED"
_ENABLE_ENV = "SIMPLICIO_AGENT_LOCAL_INFERENCE"
_LOCAL_PROVIDERS = frozenset({
    "ollama", "llamacpp", "llama.cpp", "lmstudio", "mlx", "local",
    "local-model", "vllm",
})
_LOCAL_MODEL_MARKERS = ("-mlx", ":mlx", "llama.cpp", "llamacpp")


def _is_local_endpoint(base_url: str) -> bool:
    """Small dependency-free local endpoint classifier for the early gate."""
    try:
        parsed = urlparse(base_url if "://" in base_url else f"http://{base_url}")
        host = (parsed.hostname or "").strip().lower()
    except ValueError:
        return False
    if host in {"localhost", "::1", "host.docker.internal", "host.containers.internal"}:
        return True
    if host and "." not in host:
        return True
    try:
        address = ipaddress.ip_address(host)
        return address.is_private or address.is_loopback or address.is_link_local
    except ValueError:
        return host.endswith(".local")


class LocalInferencePausedError(RuntimeError):
    """Raised before a paused local route can create side effects."""

    reason = LOCAL_INFERENCE_PAUSED

    def __init__(self, *, provider: str | None = None, base_url: str | None = None, model: str | None = None) -> None:
        self.receipt = local_inference_receipt(provider=provider, base_url=base_url, model=model)
        super().__init__(
            f"{LOCAL_INFERENCE_PAUSED}: inferência local está pausada por padrão; "
            f"nenhum runner, modelo, download ou fallback local foi iniciado. "
            f"Para reativação explícita, defina {_ENABLE_ENV}=enabled."
        )


def local_inference_enabled() -> bool:
    """Only the exact explicit opt-in value may enable a local route."""
    return os.environ.get(_ENABLE_ENV, "").strip().lower() == "enabled"


def is_local_inference_route(*, provider: str | None = None, base_url: str | None = None, model: str | None = None) -> bool:
    """Classify without probing a network endpoint, runner, or model file."""
    if str(provider or "").strip().lower() in _LOCAL_PROVIDERS:
        return True
    if base_url and _is_local_endpoint(str(base_url)):
        return True
    model_id = str(model or "").strip().lower()
    return any(marker in model_id for marker in _LOCAL_MODEL_MARKERS)


def local_inference_receipt(*, provider: str | None = None, base_url: str | None = None, model: str | None = None) -> dict[str, object]:
    """Return policy evidence without touching artifacts or the network."""
    return {
        "reason": LOCAL_INFERENCE_PAUSED,
        "enabled": local_inference_enabled(),
        "local_route": is_local_inference_route(provider=provider, base_url=base_url, model=model),
        "provider": str(provider or ""), "base_url": str(base_url or ""), "model": str(model or ""),
    }


def ensure_local_inference_allowed(*, provider: str | None = None, base_url: str | None = None, model: str | None = None) -> None:
    """Fail before transport construction when a local route is paused."""
    if is_local_inference_route(provider=provider, base_url=base_url, model=model) and not local_inference_enabled():
        raise LocalInferencePausedError(provider=provider, base_url=base_url, model=model)


__all__ = ["LOCAL_INFERENCE_PAUSED", "LocalInferencePausedError", "ensure_local_inference_allowed", "is_local_inference_route", "local_inference_enabled", "local_inference_receipt"]
