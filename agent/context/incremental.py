"""Incremental context pipeline.

Ties :class:`WorkingSet` + :class:`TfidfScorer` together: as cold handles are
indexed, the scorer learns their text; on each turn the pipeline ranks which
cold handles are worth prefetching into the hot set, then expands them.

Stdlib-only.  No LLM is required to decide what to prefetch.
"""

from __future__ import annotations

from typing import Optional

from .retrieval import TfidfScorer
from .working_set import ColdStore, WorkingSet


class IncrementalPipeline:
    """Prefetch cold handles into a working set based on query relevance.

    Parameters
    ----------
    working_set:
        The hot/cold working set to prefetch into.
    scorer:
        Optional :class:`TfidfScorer`; one is created if omitted.
    prefetch_k:
        How many top-scoring cold handles to promote each ``prefetch`` call.
    """

    def __init__(
        self,
        working_set: Optional[WorkingSet] = None,
        scorer: Optional[TfidfScorer] = None,
        prefetch_k: int = 4,
    ) -> None:
        self.ws = working_set or WorkingSet()
        self.scorer = scorer or TfidfScorer()
        self.prefetch_k = max(1, prefetch_k)

    def register(self, handle_id: str, text: str, payload: object) -> None:
        """Index a cold handle's text and stash its payload in the cold store."""
        self.scorer.index(handle_id, text)
        # stash payload in cold store (do NOT promote to hot yet)
        self.ws.stash(handle_id, payload)

    def prefetch(self, query: str) -> list[str]:
        """Promote the top-``k`` relevant cold handles into the hot set.

        Returns the list of handle ids that were promoted on this call.
        """
        top = self.scorer.top(query, k=self.prefetch_k)
        promoted: list[str] = []
        for hid, _ in top:
            if not self.ws.is_hot(hid):
                self.ws.expand(hid)
                promoted.append(hid)
        return promoted

    def expand(self, handle_id: str):
        return self.ws.expand(handle_id)
