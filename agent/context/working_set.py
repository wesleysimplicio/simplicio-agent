"""LRU hot set + cold-ref store with on-demand ``expand(handle)``.

The working set keeps a small, cheap hot set of context handles in memory and
stashes the full payloads in a cold-ref store (on disk or in a separate
mapping).  When the agent needs a payload that is not hot, it calls
``expand(handle)`` which lazily loads it back.  This keeps the per-turn system
prompt small and only pays token cost for the handles the model actually
touches.

Stdlib-only.  No LLM round-trip is required to score or expand handles.
"""

from __future__ import annotations

import hashlib
import json
import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Callable, Hashable, Optional


@dataclass
class Handle:
    """A pointer into the working set.

    ``key`` uniquely identifies the logical item (e.g. a file path, a tool
    result id, a memory slug).  ``cold_ref`` is whatever the cold store needs
    to reconstruct the payload (e.g. a path, a db id, a closure token).
    """

    key: str
    cold_ref: Any = None
    # cached hot payload; None when only the cold-ref is resident
    hot: Any = None
    token_estimate: int = 0
    content_id: str = ""


@dataclass(frozen=True)
class ContextDelta:
    """Content-addressed change set for a working-set snapshot."""

    added: tuple[str, ...]
    changed: tuple[str, ...]
    removed: tuple[str, ...]
    sha256: str

    @property
    def empty(self) -> bool:
        return not (self.added or self.changed or self.removed)

    def to_dict(self) -> dict[str, Any]:
        return {
            "added": list(self.added),
            "changed": list(self.changed),
            "removed": list(self.removed),
            "sha256": self.sha256,
            "empty": self.empty,
        }


def content_address(payload: Any) -> str:
    """Return an opaque stable id without retaining or exposing payload text."""

    if isinstance(payload, bytes):
        encoded = payload
    elif isinstance(payload, str):
        encoded = payload.encode("utf-8")
    else:
        encoded = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, default=repr
        ).encode("utf-8")
    return hashlib.blake2b(encoded, digest_size=32).hexdigest()


class ColdStore:
    """Minimal cold-ref store interface.

    The default implementation keeps payloads in an in-process dict, which is
    enough for unit tests and single-turn use.  Production wiring can subclass
    and back ``load``/``save`` with disk or a database without touching
    :class:`WorkingSet`.
    """

    def __init__(self) -> None:
        self._data: dict[Hashable, Any] = {}
        self._lock = threading.RLock()

    def save(self, ref: Any, payload: Any) -> None:
        with self._lock:
            self._data[ref] = payload

    def load(self, ref: Any) -> Optional[Any]:
        with self._lock:
            return self._data.get(ref)

    def drop(self, ref: Any) -> None:
        with self._lock:
            self._data.pop(ref, None)


class WorkingSet:
    """LRU-capped hot set over context handles with cold-ref fallback.

    Parameters
    ----------
    max_hot:
        Maximum number of handles kept hot (payloads resident in memory).
    cold:
        Cold-ref store.  Defaults to an in-memory :class:`ColdStore`.
    on_evict:
        Optional callback invoked with a :class:`Handle` when it is pushed out
        of the hot set (payload dropped, cold-ref retained).
    """

    def __init__(
        self,
        max_hot: int = 16,
        cold: Optional[ColdStore] = None,
        on_evict: Optional[Callable[[Handle], None]] = None,
    ) -> None:
        if max_hot < 1:
            raise ValueError("max_hot must be >= 1")
        self.max_hot = max_hot
        self._cold = cold or ColdStore()
        self._on_evict = on_evict
        self._hot: OrderedDict[str, Handle] = OrderedDict()
        self._content_ids: dict[str, str] = {}
        self._cold_refs: dict[str, Any] = {}
        self._lock = threading.RLock()

    # ── writes ──────────────────────────────────────────────────────────
    def stash(self, key: str, payload: Any, cold_ref: Any = None) -> None:
        """Store a payload in the cold store without promoting it hot."""
        if cold_ref is None:
            cold_ref = key
        with self._lock:
            self._cold.save(cold_ref, payload)
            self._content_ids[key] = content_address(payload)
            self._cold_refs[key] = cold_ref
            # also remember the cold_ref on the handle if it exists hot
            h = self._hot.get(key)
            if h is not None and h.cold_ref is None:
                h.cold_ref = cold_ref

    def put(
        self,
        key: str,
        payload: Any,
        cold_ref: Any = None,
        token_estimate: int = 0,
    ) -> Handle:
        """Insert or replace a handle with a hot payload."""
        if cold_ref is None:
            cold_ref = key
        with self._lock:
            self._cold.save(cold_ref, payload)
            handle = Handle(
                key=key,
                cold_ref=cold_ref,
                hot=payload,
                token_estimate=token_estimate,
                content_id=content_address(payload),
            )
            self._content_ids[key] = handle.content_id
            self._cold_refs[key] = cold_ref
            self._hot[key] = handle
            self._evict_to_cap()
            return handle

    def touch(self, key: str) -> None:
        """Mark a handle as recently used (LRU promotion)."""
        with self._lock:
            if key in self._hot:
                self._hot.move_to_end(key)

    # ── reads ───────────────────────────────────────────────────────────
    def get_hot(self, key: str) -> Optional[Handle]:
        """Return the handle if it is currently hot, else ``None``."""
        with self._lock:
            h = self._hot.get(key)
            if h is not None:
                self._hot.move_to_end(key)
            return h

    def expand(self, key: str) -> Optional[Any]:
        """Return the payload for ``key``, loading from cold store if needed.

        Returns ``None`` when the key is unknown to both hot and cold stores.
        On a cold hit, the handle is re-promoted into the hot set (respecting
        the LRU cap).
        """
        with self._lock:
            h = self._hot.get(key)
            if h is not None:
                self._hot.move_to_end(key)
                return h.hot
            payload = self._cold.load(self._cold_refs.get(key, key))
            if payload is None:
                return None
            # cold hit → promote
            h = Handle(
                key=key,
                cold_ref=self._cold_refs.get(key, key),
                hot=payload,
                content_id=self._content_ids.get(key, content_address(payload)),
            )
            self._hot[key] = h
            self._evict_to_cap()
            return payload

    def is_hot(self, key: str) -> bool:
        with self._lock:
            return key in self._hot

    def keys_hot(self) -> list[str]:
        with self._lock:
            return list(self._hot.keys())

    def snapshot(self) -> dict[str, str]:
        """Return opaque content ids for all registered handles."""

        with self._lock:
            return dict(sorted(self._content_ids.items()))

    def delta(self, previous: Optional[dict[str, str]] = None) -> ContextDelta:
        """Compare the current content-addressed snapshot with ``previous``."""

        before = previous or {}
        after = self.snapshot()
        added = tuple(sorted(set(after) - set(before)))
        removed = tuple(sorted(set(before) - set(after)))
        changed = tuple(
            sorted(key for key in set(after) & set(before) if after[key] != before[key])
        )
        payload = json.dumps(
            {"added": added, "changed": changed, "removed": removed},
            separators=(",", ":"),
        ).encode("utf-8")
        return ContextDelta(
            added=added,
            changed=changed,
            removed=removed,
            sha256=hashlib.sha256(payload).hexdigest(),
        )

    def __len__(self) -> int:
        with self._lock:
            return len(self._hot)

    # ── internals ─────────────────────────────────────────────────────────
    def _evict_to_cap(self) -> None:
        while len(self._hot) > self.max_hot:
            old_key, old_handle = self._hot.popitem(last=False)
            old_handle.hot = None  # drop payload, keep cold_ref
            if self._on_evict is not None:
                self._on_evict(old_handle)


def expand(working_set: WorkingSet, key: str) -> Optional[Any]:
    """Free-function wrapper around :meth:`WorkingSet.expand`."""
    return working_set.expand(key)
