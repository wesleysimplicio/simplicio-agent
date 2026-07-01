"""Helpers for reading the effective fallback provider chain from config."""

from __future__ import annotations

from typing import Any, Callable


def _normalized_base_url(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip().rstrip("/")


def _iter_fallback_entries(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, dict):
        candidates = [raw]
    elif isinstance(raw, list):
        candidates = raw
    else:
        return []

    entries: list[dict[str, Any]] = []
    for entry in candidates:
        if not isinstance(entry, dict):
            continue
        provider = str(entry.get("provider") or "").strip()
        model = str(entry.get("model") or "").strip()
        if not provider or not model:
            continue

        normalized = dict(entry)
        normalized["provider"] = provider
        normalized["model"] = model

        base_url = _normalized_base_url(entry.get("base_url"))
        if base_url:
            normalized["base_url"] = base_url

        entries.append(normalized)
    return entries


def _entry_identity(entry: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(entry.get("provider") or "").strip().lower(),
        str(entry.get("model") or "").strip().lower(),
        _normalized_base_url(entry.get("base_url")).lower(),
    )


def get_fallback_chain(config: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Return the effective fallback chain merged across old and new config keys.

    ``fallback_providers`` remains the primary source of truth and keeps its
    order. Legacy ``fallback_model`` entries are appended afterwards unless
    they target the same provider/model/base_url route as an earlier entry.
    The returned list always contains fresh dict copies.
    """

    config = config or {}
    chain: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    for key in ("fallback_providers", "fallback_model"):
        for entry in _iter_fallback_entries(config.get(key)):
            identity = _entry_identity(entry)
            if identity in seen:
                continue
            seen.add(identity)
            chain.append(entry)

    return chain


def is_transient_fallback_error(exc: BaseException) -> bool:
    """Classify whether *exc* is worth retrying the same fallback provider.

    ``get_fallback_chain`` above only merges config into an ordered list of
    provider entries — it has no notion of which errors are transient (worth
    a retry before moving on) versus fatal (skip straight to the next
    provider). ``agent.providers.is_transient`` already implements exactly
    that heuristic (rate limits, timeouts, 5xx, etc.) for the ported
    ``ProviderChain``. This thin re-export lets any caller iterating
    ``get_fallback_chain()``'s entries (e.g. a future retry loop around
    ``gateway.run._try_resolve_fallback_provider``) adopt the same
    classifier instead of re-deriving it, without requiring that caller to
    run the full ``ProviderChain`` execution model.
    """
    from agent.providers import is_transient

    return is_transient(exc)


def build_fallback_provider_chain(
    config: dict[str, Any] | None,
    call_provider: Callable[[dict[str, Any], str], object],
    *,
    max_retries: int = 3,
    base_delay_s: float = 0.5,
    max_delay_s: float = 8.0,
):
    """Build a ``ProviderChain`` from this module's merged config chain.

    Opt-in, additive helper: ``get_fallback_chain`` returns plain config
    dicts with no execution behavior — callers resolve credentials and try
    each entry themselves with no shared retry/backoff/metrics policy. This
    wraps the same merged chain (``get_fallback_chain(config)``) in
    ``agent.providers.ProviderChain`` so a caller that wants jittered
    exponential backoff, transient-vs-fatal classification, and attempt
    metrics can get it "for free" instead of hand-rolling a retry loop.

    ``call_provider`` receives ``(entry, prompt)`` for each config entry
    (the same dicts ``get_fallback_chain`` produces) and must return the
    provider's response or raise. Nothing in the existing gateway/CLI code
    calls this yet — it is a new capability a caller can adopt, not a
    replacement for ``get_fallback_chain`` or any existing fallback call site.
    """
    from agent.providers import ProviderChain

    entries = get_fallback_chain(config)
    providers: list[tuple[str, Callable[[str], object]]] = []
    for entry in entries:
        name = str(entry.get("provider") or entry.get("model") or "unknown")

        def _call(prompt: str, _entry: dict[str, Any] = entry) -> object:
            return call_provider(_entry, prompt)

        providers.append((name, _call))

    return ProviderChain(
        providers=providers,
        max_retries=max_retries,
        base_delay_s=base_delay_s,
        max_delay_s=max_delay_s,
    )
