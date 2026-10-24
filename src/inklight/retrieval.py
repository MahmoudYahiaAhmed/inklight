"""Hybrid retrieval: SQLite FTS5 BM25 always; semantic vectors when the embedder is installed."""

from __future__ import annotations

import logging

import numpy as np

from .brains import Brain
from .schemas import SearchHit
from .store import Store
from .textnorm import mostly_arabic

log = logging.getLogger(__name__)
RRF_K = 60
SCOPE_FALLBACK_DOCS = 2


class Retriever:
    def __init__(self, store: Store, brain: Brain) -> None:
        self.store = store
        self.brain = brain

    def index_embeddings(self) -> int:
        """Embed chunks that have no vector yet. Returns how many were added."""
        embedder = self.brain.embedder
        if embedder is None:
            return 0
        missing = self.store.missing_embeddings(embedder.name)
        if not missing:
            return 0
        vectors = embedder.embed([text[:2000] for _, text in missing])
        self.store.save_embeddings(embedder.name, [(cid, vectors[i]) for i, (cid, _) in enumerate(missing)])
        return len(missing)

    def search(self, query: str, doc_ids: list[str] | None = None, k: int = 8) -> list[SearchHit]:
        keyword = self.store.keyword_search(query, doc_ids, limit=k * 3)
        semantic: list[tuple[int, float]] = []
        # The embedder is an English model. On Arabic queries it ranked the right document lower than keyword
        # search alone (bench/usecases/retrieval_ablation.py), so Arabic queries are keyword-only.
        embedder = None if mostly_arabic(query) else self.brain.embedder
        if not keyword and doc_ids and len(doc_ids) <= SCOPE_FALLBACK_DOCS:
            # A question about one or two named documents that shares no indexed word with them (Arabic
            # inflection, a synonym): read their passages in order rather than answer "nothing found".
            scoped = self.store.chunks_for(doc_ids)[:k]
            if scoped and embedder is None:
                return [SearchHit(source=src, score=0.0, method="scope") for _, src in scoped]
        if embedder is not None:
            try:
                self.index_embeddings()
                ids, matrix = self.store.embeddings(embedder.name, doc_ids)
                if ids:
                    sims = matrix @ embedder.embed([query], query=True)[0]
                    order = np.argsort(sims)[::-1][: k * 3]
                    semantic = [(ids[i], float(sims[i])) for i in order]
            except Exception as exc:  # semantic search is an enhancement, never a hard dependency
                log.warning("semantic search failed, keyword only: %s", exc)
        if not semantic:
            return [
                SearchHit(source=src.model_copy(update={"score": src.score}), score=src.score or 0.0, method="keyword")
                for _, src in keyword[:k]
            ]
        fused: dict[int, float] = {}
        for rank, (cid, _) in enumerate(keyword):
            fused[cid] = fused.get(cid, 0.0) + 1.0 / (RRF_K + rank)
        for rank, (cid, _) in enumerate(semantic):
            fused[cid] = fused.get(cid, 0.0) + 1.0 / (RRF_K + rank)
        top = sorted(fused, key=lambda c: fused[c], reverse=True)[:k]
        sources = self.store.chunk_sources(top)
        method = "hybrid" if keyword else "semantic"
        return [
            SearchHit(
                source=sources[c].model_copy(update={"score": round(fused[c], 5)}),
                score=round(fused[c], 5),
                method=method,
            )
            for c in top
            if c in sources
        ]
