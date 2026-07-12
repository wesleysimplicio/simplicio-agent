"""Testes do cache incremental de discovery (issue #226)."""
from __future__ import annotations

import os
import tempfile

import pytest

from tools.discovery_cache import (
    DiscoveryCache,
    DiscoverySource,
    LazyToolBackend,
    sync_discovery,
)


@pytest.fixture
def cache_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


def _write(path, content="x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)


def test_cold_start_populates_cache(cache_dir):
    src_file = os.path.join(cache_dir, "skill_a", "SKILL.md")
    _write(src_file)
    src = DiscoverySource(src_file, subtree_root=os.path.dirname(src_file))
    cache = DiscoveryCache(cache_dir=cache_dir, profile="p1")
    calls = {"n": 0}

    def parse(s):
        calls["n"] += 1
        return {"name": "a"}

    out = sync_discovery([("a", src)], parse, cache)
    assert out["a"] == {"name": "a"}
    assert calls["n"] == 1  # reparsou no cold start


def test_second_start_skips_intact_parse(cache_dir):
    src_file = os.path.join(cache_dir, "skill_a", "SKILL.md")
    _write(src_file)
    src = DiscoverySource(src_file, subtree_root=os.path.dirname(src_file))
    cache = DiscoveryCache(cache_dir=cache_dir, profile="p1")
    calls = {"n": 0}

    def parse(s):
        calls["n"] += 1
        return {"name": "a"}

    sync_discovery([("a", src)], parse, cache)
    # segundo startup: arquivo intacto -> NÃO reparsa
    sync_discovery([("a", src)], parse, cache)
    assert calls["n"] == 1


def test_alter_one_file_invalidates_only_subtree(cache_dir):
    fa = os.path.join(cache_dir, "skill_a", "SKILL.md")
    fb = os.path.join(cache_dir, "skill_b", "SKILL.md")
    _write(fa)
    _write(fb)
    sa = DiscoverySource(fa, subtree_root=os.path.dirname(fa))
    sb = DiscoverySource(fb, subtree_root=os.path.dirname(fb))
    cache = DiscoveryCache(cache_dir=cache_dir, profile="p1")
    calls = {"n": 0}

    def parse(s):
        calls["n"] += 1
        return {"name": os.path.basename(os.path.dirname(s.path))}

    sync_discovery([("a", sa), ("b", sb)], parse, cache)
    assert calls["n"] == 2
    # altera só skill_a
    _write(fa, "changed")
    sa2 = DiscoverySource(fa, subtree_root=os.path.dirname(fa))
    sync_discovery([("a", sa2), ("b", sb)], parse, cache)
    # só 'a' reparsado (b intacto)
    assert calls["n"] == 3


def test_lazy_backend_imports_once(cache_dir):
    backend = LazyToolBackend()
    imports = {"n": 0}

    def importer():
        imports["n"] += 1
        return object()

    backend.resolve("tool_x", importer)
    backend.resolve("tool_x", importer)
    assert imports["n"] == 1


def test_corrupt_manifest_rebuilds_failopen(cache_dir):
    # escreve manifest corrompido
    os.makedirs(cache_dir, exist_ok=True)
    with open(os.path.join(cache_dir, "discovery_cache.json"), "w") as f:
        f.write("{not json")
    cache = DiscoveryCache(cache_dir=cache_dir, profile="p1")
    assert cache.get("anything") is None  # fail-open, não quebra
