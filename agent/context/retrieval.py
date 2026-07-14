"""TF-IDF scorer (stdlib only) to prioritize which handles to expand.

Given a query string (e.g. the current user turn) and a set of candidate
handles, score each candidate's text so the working set can prefetch the most
relevant cold payloads before the model needs them.  Pure-Python TF-IDF over
counted term frequencies — no numpy, no LLM.

The scorer is intentionally tiny: it is called on the mechanical path, so it
must be fast and dependency-free.
"""

from __future__ import annotations

import math
import re
from collections import Counter

_TOKEN_RE = re.compile(r"[a-z0-9_]+")


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


class TfidfScorer:
    """Incremental TF-IDF over a corpus of candidate documents.

    Call :meth:`index` once per candidate handle with its id and text.  Then
    call :meth:`score` with a query to get a ``dict`` of ``handle_id -> score``
    for the handles that share terms with the query.  Handles with no term
    overlap score 0 and are omitted.
    """

    def __init__(self) -> None:
        self._docs: dict[str, Counter[str]] = {}
        self._df: Counter[str] = Counter()
        self._n: int = 0

    def index(self, handle_id: str, text: str) -> None:
        """Add/replace a candidate document for ``handle_id``."""
        tf = Counter(_tokenize(text))
        if not tf:
            return
        self._docs[handle_id] = tf
        for term in tf:
            self._df[term] += 1
        self._n += 1

    def forget(self, handle_id: str) -> None:
        tf = self._docs.pop(handle_id, None)
        if tf is None:
            return
        for term in tf:
            self._df[term] -= 1
            if self._df[term] <= 0:
                del self._df[term]
        self._n = max(0, self._n - 1)

    def score(self, query: str) -> dict[str, float]:
        """Return ``{handle_id: tfidf_score}`` for overlapping handles."""
        if self._n == 0:
            return {}
        q_tf = Counter(_tokenize(query))
        if not q_tf:
            return {}
        out: dict[str, float] = {}
        for hid, tf in self._docs.items():
            total = sum(tf.values())
            acc = 0.0
            for term, q_count in q_tf.items():
                doc_count = tf.get(term)
                if not doc_count:
                    continue
                idf = math.log((self._n + 1) / (self._df.get(term, 0) + 1)) + 1.0
                acc += (doc_count / total) * idf * q_count
            if acc > 0.0:
                out[hid] = acc
        return out

    def top(self, query: str, k: int = 5) -> list[tuple[str, float]]:
        """Return the ``k`` highest-scoring ``(handle_id, score)`` pairs."""
        ranked = sorted(self.score(query).items(), key=lambda kv: kv[1], reverse=True)
        return ranked[:k]
