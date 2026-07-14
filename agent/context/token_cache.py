"""Incremental token cache (blake2b, model-scoped, LRU).

Caches serialized prompt fragments keyed by a content hash so repeated prefix
assembly reuses cached tokenization/encoding work instead of recomputing it
every turn.  Scoped per ``model`` because tokenizers differ across models.

Stdlib-only (``hashlib.blake2b`` + an ``OrderedDict`` LRU).  The cache is
process-local; wiring it to a shared store is out of scope here but the API is
stable.
"""

from __future__ import annotations

import hashlib
import threading
from collections import OrderedDict
from typing import Hashable, Optional


def content_key(model: str, text: str) -> str:
    """Stable cache key for ``(model, text)``."""
    h = hashlib.blake2b(digest_size=16)
    h.update(model.encode("utf-8"))
    h.update(b"\x00")
    h.update(text.encode("utf-8"))
    return h.hexdigest()


class TokenCache:
    """Model-scoped, LRU-capped cache of encoded token sequences."""

    def __init__(self, max_entries: int = 4096) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be >= 1")
        self.max_entries = max_entries
        self._store: OrderedDict[str, list[int]] = OrderedDict()
        self._lock = threading.RLock()

    def get(self, model: str, text: str) -> Optional[list[int]]:
        key = content_key(model, text)
        with self._lock:
            if key in self._store:
                self._store.move_to_end(key)
                return list(self._store[key])  # copy to avoid mutability leaks
            return None

    def put(self, model: str, text: str, tokens: list[int]) -> str:
        key = content_key(model, text)
        with self._lock:
            self._store[key] = list(tokens)
            self._store.move_to_end(key)
            while len(self._store) > self.max_entries:
                self._store.popitem(last=False)
            return key

    def __contains__(self, item: tuple[str, str]) -> bool:
        model, text = item
        with self._lock:
            return content_key(model, text) in self._store

    def __len__(self) -> int:
        with self._lock:
            return len(self._store)
