"""Cache incremental content-addressed para discovery de skills/plugins/MCP/tools.

Objetivo (issue #226): evitar reparse/import de entradas intactas no segundo
startup. O manifest é por perfil, gravado atomicamente, e fail-open (corrompido
ou legado reconstrói sem bloquear UX).

Design:
    - fingerprint por arquivo (SHA-256 de conteúdo + deps)
    - cache machine-readable por profile ($SIMPLICIO_AGENT_HOME/cache/discovery_cache.json)
    - invalidação seletiva: mudar 1 arquivo invalida só sua subárvore
    - import do backend só quando a capability é selecionada (LazyToolBackend)

Não quebra health/readiness: sync_discovery reparsa SÓ entradas com drift e
sempre retorna o dicionário completo key->metadata (fallback incondicional).
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple


class DiscoverySource:
    """Um arquivo/capability cujo fingerprint queremos rastrear."""

    def __init__(self, path: str, deps: Optional[List[str]] = None, subtree_root: str = ""):
        self.path = path
        self.deps = deps or []
        self.subtree_root = subtree_root or os.path.dirname(path)

    def fingerprint(self) -> str:
        h = hashlib.sha256()
        try:
            with open(self.path, "rb") as f:
                for chunk in iter(lambda: f.read(65536), b""):
                    h.update(chunk)
        except OSError:
            h.update(self.path.encode())
        for d in self.deps:
            h.update(b"\x00")
            h.update(d.encode())
        return h.hexdigest()


@dataclass
class _Entry:
    fingerprint: str
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"fingerprint": self.fingerprint, "metadata": self.metadata}

    @classmethod
    def from_dict(cls, d: dict) -> "_Entry":
        return cls(fingerprint=d.get("fingerprint", ""), metadata=d.get("metadata", {}))


class DiscoveryCache:
    """Manifest content-addressed por perfil."""

    def __init__(self, cache_dir: Optional[str] = None, profile: str = "default"):
        if cache_dir is None:
            root = os.environ.get("SIMPLICIO_AGENT_HOME") or os.environ.get("HERMES_HOME") or os.path.expanduser("~/.simplicio_agent")
            cache_dir = os.path.join(root, "cache")
        self.cache_dir = cache_dir
        self.profile = profile
        self.path = os.path.join(cache_dir, "discovery_cache.json")
        self._store: Dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict) or data.get("schema") != "discovery-cache/v1":
                self._store = {}
                return
            profiles = data.get("profiles", {})
            self._store = profiles.get(self.profile, {})
        except (OSError, json.JSONDecodeError, ValueError):
            # fail-open: manifest corrompido/legado reconstrói vazio
            self._store = {}

    def _save(self) -> None:
        os.makedirs(self.cache_dir, exist_ok=True)
        tmp = self.path + ".tmp"
        data = {"schema": "discovery-cache/v1", "profiles": {self.profile: self._store}}
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f)
            os.replace(tmp, self.path)
        except OSError:
            pass  # fail-open

    def get(self, key: str) -> Optional[dict]:
        e = self._store.get(key)
        return e["metadata"] if e else None

    def has(self, key: str, source: "DiscoverySource") -> bool:
        e = self._store.get(key)
        if not e:
            return False
        return e.get("fingerprint") == source.fingerprint()

    def put(self, key: str, source: "DiscoverySource", metadata: dict) -> None:
        self._store[key] = _Entry(source.fingerprint(), metadata).to_dict()

    def invalidate_subtree(self, subtree_root: str) -> List[str]:
        removed = [k for k, v in self._store.items() if v.get("subtree_root") == subtree_root]
        for k in removed:
            del self._store[k]
        if removed:
            self._save()
        return removed

    def save(self) -> None:
        self._save()


def sync_discovery(
    sources: List[Tuple[str, DiscoverySource]],
    parse: Callable[[DiscoverySource], dict],
    cache: DiscoveryCache,
) -> Dict[str, dict]:
    """Reparse SÓ entradas com drift; retorna dicionário completo key->metadata."""
    result: Dict[str, dict] = {}
    changed = False
    for key, src in sources:
        if cache.has(key, src):
            cached = cache.get(key)
            result[key] = cached if cached is not None else {}  # intacta: não reparsa
        else:
            meta = parse(src)
            cache.put(key, src, meta)
            result[key] = meta
            changed = True
    if changed:
        cache.save()
    return result


class LazyToolBackend:
    """Import do backend só quando a capability é selecionada."""

    def __init__(self) -> None:
        self._imported: Dict[str, object] = {}

    def resolve(self, name: str, importer: Callable[[], object]) -> object:
        if name not in self._imported:
            self._imported[name] = importer()
        return self._imported[name]
