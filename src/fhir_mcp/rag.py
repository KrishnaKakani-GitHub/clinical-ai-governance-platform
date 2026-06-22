"""Hybrid RAG over clinical guidelines.

Implements a two-stage retrieval pipeline:
  Stage 1 - BM25 (rank-bm25): sparse keyword retrieval, zero infrastructure.
  Stage 2 - ChromaDB: dense semantic retrieval via sentence embeddings.
  Merge  - Reciprocal Rank Fusion (RRF): combines both ranked lists.

This is the Anthropic course pattern: BM25 for precision on clinical terms
(LOINC codes, drug names, numeric thresholds), embeddings for semantic
generalisation ("high blood pressure" → "hypertension").

ChromaDB is optional: set FHIR_MCP_RAG_DISABLE_CHROMA=1 to run BM25-only
(used in CI to avoid ONNX runtime startup overhead).

Prompt caching integration (Day 3):
  The build_context_block() method returns a dict with cache_control
  breakpoints so the retrieved guidelines block can be cached across
  repeated proposals for the same patient session.

Production path: ChromaDB → pgvector (see ADR-004).

PHI NOTE: This module operates on clinical guidelines only — not patient data.
No PHI touchpoints.
"""
from __future__ import annotations

import json
import math
import os
import re
from pathlib import Path
from typing import Any

_GUIDELINES_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "clinical_guidelines.json"
)
_DISABLE_CHROMA = os.environ.get("FHIR_MCP_RAG_DISABLE_CHROMA", "0") == "1"


def _tokenise(text: str) -> list[str]:
    """Simple whitespace + punctuation tokeniser. LOINC codes kept intact."""
    return re.findall(r"[\w.\-]+", text.lower())


class ClinicalRAG:
    """Hybrid BM25 + ChromaDB retrieval over clinical guidelines.

    Usage:
        rag = ClinicalRAG()
        rag.load_guidelines()  # or pass path to load_guidelines(path)
        results = rag.search_guidelines("elevated heart rate in AF", k=3)
        for r in results:
            print(r["score"], r["guideline"]["title"])
    """

    def __init__(
        self,
        guidelines_path: Path = _GUIDELINES_PATH,
        alpha: float = 0.5,
        disable_chroma: bool = _DISABLE_CHROMA,
    ) -> None:
        """Args:
            guidelines_path: Path to clinical_guidelines.json.
            alpha: Weight for BM25 in RRF fusion. 0=chroma-only, 1=bm25-only.
            disable_chroma: Skip ChromaDB (BM25-only mode, good for CI).
        """
        self._guidelines_path = guidelines_path
        self._alpha = alpha
        self._disable_chroma = disable_chroma
        self._guidelines: list[dict[str, Any]] = []
        self._bm25: Any | None = None
        self._corpus_tokens: list[list[str]] = []
        self._chroma_collection: Any | None = None
        self._loaded = False

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def load_guidelines(
        self,
        path: Path | None = None,
        guidelines: list[dict[str, Any]] | None = None,
    ) -> None:
        """Load guidelines from JSON file or a pre-built list (for tests)."""
        if guidelines is not None:
            self._guidelines = guidelines
        else:
            src = path or self._guidelines_path
            self._guidelines = json.loads(src.read_text(encoding="utf-8"))

        self._build_bm25()
        if not self._disable_chroma:
            self._build_chroma()
        self._loaded = True

    def _build_bm25(self) -> None:
        try:
            from rank_bm25 import BM25Okapi
        except ImportError as e:
            raise ImportError("rank-bm25 is required: pip install rank-bm25") from e

        self._corpus_tokens = [
            _tokenise(g["title"] + " " + g["content"]) for g in self._guidelines
        ]
        self._bm25 = BM25Okapi(self._corpus_tokens)

    def _build_chroma(
        self,
        collection_name: str = "clinical_guidelines",
    ) -> None:
        try:
            import chromadb  # type: ignore[import-untyped]
        except ImportError as e:
            raise ImportError("chromadb is required: pip install chromadb") from e

        client = chromadb.EphemeralClient()
        # Delete + recreate to keep load_guidelines idempotent
        try:
            client.delete_collection(collection_name)
        except Exception:
            pass
        coll = client.create_collection(collection_name)
        docs = [g["title"] + " " + g["content"] for g in self._guidelines]
        ids = [g["id"] for g in self._guidelines]
        coll.add(documents=docs, ids=ids)
        self._chroma_collection = coll

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search_guidelines(
        self,
        query: str,
        k: int = 4,
        loinc_filter: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Retrieve the top-k guidelines relevant to `query`.

        Args:
            query:        Free-text clinical question.
            k:            Number of results to return.
            loinc_filter: If provided, only return guidelines that reference
                          at least one of these LOINC codes.

        Returns:
            List of dicts with keys: score (float), rank (int), guideline (dict).
            Sorted by descending RRF score.
        """
        if not self._loaded:
            self.load_guidelines()

        candidates = self._guidelines
        if loinc_filter:
            loinc_set = set(loinc_filter)
            candidates = [
                g for g in candidates
                if loinc_set.intersection(g.get("loinc_codes", []))
            ]
            if not candidates:
                return []

        query_tokens = _tokenise(query)
        bm25_scores = self._bm25_scores(query_tokens, candidates)
        chroma_scores = self._chroma_scores(query, candidates)

        # Reciprocal Rank Fusion
        rrf_scores = self._rrf_merge(bm25_scores, chroma_scores, self._alpha)

        # Sort and return top-k
        indexed = sorted(enumerate(rrf_scores), key=lambda x: x[1], reverse=True)
        results = []
        for rank, (idx, score) in enumerate(indexed[:k], start=1):
            results.append({
                "score": round(score, 4),
                "rank": rank,
                "guideline": candidates[idx],
            })
        return results

    def _bm25_scores(
        self,
        query_tokens: list[str],
        candidates: list[dict[str, Any]],
    ) -> list[float]:
        if self._bm25 is None or not candidates:
            return [0.0] * len(candidates)

        # If candidates is the full set, use BM25 directly
        if len(candidates) == len(self._guidelines):
            raw = self._bm25.get_scores(query_tokens)
            return list(raw)

        # Subset: rebuild BM25 on the filtered candidates
        from rank_bm25 import BM25Okapi
        tokens = [
            _tokenise(g["title"] + " " + g["content"]) for g in candidates
        ]
        bm25 = BM25Okapi(tokens)
        return list(bm25.get_scores(query_tokens))

    def _chroma_scores(
        self,
        query: str,
        candidates: list[dict[str, Any]],
    ) -> list[float]:
        if self._disable_chroma or self._chroma_collection is None or not candidates:
            return [0.0] * len(candidates)

        candidate_ids = {g["id"] for g in candidates}
        result = self._chroma_collection.query(
            query_texts=[query],
            n_results=min(len(candidates), max(1, len(self._guidelines))),
            include=["distances"],
        )
        # Build id → similarity score map
        # ChromaDB returns L2 distance; convert to similarity: 1 / (1 + d)
        id_score: dict[str, float] = {}
        if result["ids"]:
            for cid, dist in zip(result["ids"][0], result["distances"][0]):
                if cid in candidate_ids:
                    id_score[cid] = 1.0 / (1.0 + dist)

        return [id_score.get(g["id"], 0.0) for g in candidates]

    @staticmethod
    def _rrf_merge(
        bm25_scores: list[float],
        chroma_scores: list[float],
        alpha: float,
        k: int = 60,
    ) -> list[float]:
        """Reciprocal Rank Fusion.

        RRF(d) = alpha * 1/(rank_bm25(d) + k) + (1 - alpha) * 1/(rank_chroma(d) + k)
        """
        n = len(bm25_scores)
        if n == 0:
            return []

        def _ranks(scores: list[float]) -> list[int]:
            sorted_idx = sorted(range(n), key=lambda i: scores[i], reverse=True)
            ranks = [0] * n
            for rank, idx in enumerate(sorted_idx, start=1):
                ranks[idx] = rank
            return ranks

        bm25_ranks = _ranks(bm25_scores)
        chroma_ranks = _ranks(chroma_scores)

        return [
            alpha * (1.0 / (bm25_ranks[i] + k))
            + (1.0 - alpha) * (1.0 / (chroma_ranks[i] + k))
            for i in range(n)
        ]

    # ------------------------------------------------------------------
    # Prompt caching helper
    # ------------------------------------------------------------------

    def build_context_block(
        self,
        results: list[dict[str, Any]],
        *,
        cache: bool = True,
    ) -> dict[str, Any]:
        """Build an Anthropic content block from search results.

        Returns a dict suitable for inclusion in a messages[] content array.
        When cache=True, adds a cache_control breakpoint so the guidelines
        context is reused across multiple tool calls in the same session.
        """
        if not results:
            text = "No relevant clinical guidelines found for this query."
        else:
            lines = ["Relevant clinical guidelines (ranked by relevance):"]
            for r in results:
                g = r["guideline"]
                lines.append(
                    f"\n[Rank {r['rank']}, score {r['score']}] "
                    f"{g['title']} ({g['source']})\n"
                    f"Condition: {g['condition']} | "
                    f"LOINC codes: {', '.join(g.get('loinc_codes', []))}\n"
                    f"{g['content']}"
                )
            text = "\n".join(lines)

        block: dict[str, Any] = {"type": "text", "text": text}
        if cache:
            block["cache_control"] = {"type": "ephemeral"}
        return block


# Module-level singleton for server.py to use
_rag: ClinicalRAG | None = None


def get_rag() -> ClinicalRAG:
    """Return the module-level RAG instance, initialised on first call."""
    global _rag
    if _rag is None:
        _rag = ClinicalRAG()
        _rag.load_guidelines()
    return _rag
