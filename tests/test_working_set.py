"""Tests for the agent.context working-set capability (Turbo #92, built here)."""

import sys
from pathlib import Path

import pytest

# make agent importable when run from repo root
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent.context import (  # noqa: E402
    CacheReceipt,
    ColdStore,
    ContextDelta,
    Handle,
    IncrementalPipeline,
    TfidfScorer,
    TokenCache,
    WorkingSet,
    expand,
)


def test_put_and_hot_read():
    ws = WorkingSet(max_hot=4)
    h = ws.put("a", "payload-a", token_estimate=10)
    assert isinstance(h, Handle)
    assert ws.is_hot("a")
    assert ws.get_hot("a").hot == "payload-a"
    assert ws.expand("a") == "payload-a"


def test_expand_cold_hit_promotes():
    cold = ColdStore()
    cold.save("c", "payload-c")
    ws = WorkingSet(max_hot=2, cold=cold)
    # not hot yet
    assert not ws.is_hot("c")
    # expand loads from cold and promotes
    assert ws.expand("c") == "payload-c"
    assert ws.is_hot("c")


def test_expand_unknown_returns_none():
    ws = WorkingSet()
    assert ws.expand("nope") is None


def test_lru_eviction_drops_payload_keeps_cold():
    evicted = []
    ws = WorkingSet(max_hot=2, on_evict=lambda h: evicted.append(h.key))
    ws.put("a", "A")
    ws.put("b", "B")
    ws.put("c", "C")  # evicts "a"
    assert not ws.is_hot("a")
    assert "a" in evicted
    # cold ref retained → expand still works
    assert ws.expand("a") == "A"


def test_lru_promotion_order():
    ws = WorkingSet(max_hot=2)
    ws.put("a", "A")
    ws.put("b", "B")
    ws.touch("a")  # a now most-recent
    ws.put("c", "C")  # should evict b, not a
    assert ws.is_hot("a")
    assert not ws.is_hot("b")
    assert ws.is_hot("c")


def test_free_function_expand():
    ws = WorkingSet()
    ws.put("x", "X")
    assert expand(ws, "x") == "X"


def test_tfidf_ranking_prefers_overlap():
    s = TfidfScorer()
    s.index("doc1", "rust cargo build release profile")
    s.index("doc2", "python pip install requirements virtualenv")
    scores = s.score("how to build a rust release binary")
    assert "doc1" in scores
    assert "doc2" not in scores  # no term overlap
    assert scores["doc1"] > 0


def test_tfidf_top_k():
    s = TfidfScorer()
    for i in range(10):
        s.index(f"d{i}", f"keyword{i} unrelated padding text {i}")
    s.index("target", "rust cargo build release")
    top = s.top("rust cargo build release", k=3)
    assert top[0][0] == "target"


def test_token_cache_hit_miss():
    tc = TokenCache(max_entries=8)
    assert tc.get("gpt", "hello") is None
    tc.put("gpt", "hello", [1, 2, 3])
    assert tc.get("gpt", "hello") == [1, 2, 3]
    # different model → miss (tokenizer scoped)
    assert tc.get("claude", "hello") is None
    assert ("gpt", "hello") in tc


def test_token_cache_lru_evicts():
    tc = TokenCache(max_entries=2)
    tc.put("m", "a", [1])
    tc.put("m", "b", [2])
    tc.put("m", "c", [3])  # evicts "a"
    assert ("m", "a") not in tc
    assert ("m", "c") in tc


def test_pipeline_prefetch_promotes_relevant():
    pipe = IncrementalPipeline(prefetch_k=2)
    pipe.register("rust_doc", "rust cargo build release profile lto", "RUST_PAYLOAD")
    pipe.register("py_doc", "python pip install requirements", "PY_PAYLOAD")
    pipe.register("go_doc", "golang module build compile", "GO_PAYLOAD")
    promoted = pipe.prefetch("compile a rust release with cargo")
    assert "rust_doc" in promoted
    assert pipe.ws.is_hot("rust_doc")
    # py_doc had no overlap → not promoted
    assert "py_doc" not in promoted


def test_pipeline_expand_after_register():
    pipe = IncrementalPipeline()
    pipe.register("h", "some text about caching tokens", "PAYLOAD_H")
    # not prefetched by an unrelated query
    assert not pipe.ws.is_hot("h")
    # direct expand loads it
    assert pipe.expand("h") == "PAYLOAD_H"


def test_working_set_content_ids_and_deterministic_delta():
    ws = WorkingSet()
    before = ws.snapshot()
    ws.put("doc", "payload-v1")
    first = ws.delta(before)
    assert isinstance(first, ContextDelta)
    assert first.added == ("doc",)
    before = ws.snapshot()
    ws.put("doc", "payload-v2")
    changed = ws.delta(before)
    assert changed.changed == ("doc",)
    assert changed.sha256 == ws.delta(before).sha256
    assert "payload-v2" not in changed.to_dict()["sha256"]


def test_token_cache_receipts_are_model_scoped_and_content_free():
    cache = TokenCache(max_entries=2)
    miss, miss_receipt = cache.get_with_receipt("model-a", "secret prompt")
    assert miss is None
    assert isinstance(miss_receipt, CacheReceipt)
    assert not miss_receipt.hit
    receipt = cache.put_with_receipt("model-a", "secret prompt", [1, 2])
    assert receipt.key == miss_receipt.key
    hit, hit_receipt = cache.get_with_receipt("model-a", "secret prompt")
    assert hit == [1, 2]
    assert hit_receipt.hit
    assert "secret prompt" not in hit_receipt.to_dict()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
