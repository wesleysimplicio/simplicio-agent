"""Context working-set: hot LRU handles + cold-ref store with on-demand expand.

Implements the Simplicio Agent ``working_set`` capability (Turbo issue #92,
spec-only in upstream — built here).  Stdlib-only so it can run inside the
agent core without pulling heavy dependencies into the per-call path.
"""

from __future__ import annotations

from .working_set import (
    ColdStore,
    ContextDelta,
    Handle,
    WorkingSet,
    content_address,
    expand,
)
from .retrieval import TfidfScorer
from .token_cache import CacheReceipt, TokenCache
from .incremental import IncrementalPipeline

__all__ = [
    "ColdStore",
    "CacheReceipt",
    "ContextDelta",
    "Handle",
    "WorkingSet",
    "content_address",
    "expand",
    "TfidfScorer",
    "TokenCache",
    "IncrementalPipeline",
]
