"""Vetted Argo Knowledge Base — RAG-lite.

Loads a local JSON file with 15-20 Q&A entries based on official Argo documentation
(argodatamgt.org/Documentation). Provides lightweight matching (TF-IDF cosine + fuzzy overlap)
to retrieve the most relevant entry for a KNOWLEDGE_QUERY without any external LLM hallucination.

Non-negotiables:
- No web scraping.
- Only returns vetted local text.
- If no entry matches well, caller should fallback safely.
"""

from __future__ import annotations

import json
import logging
import math
import re
from pathlib import Path
from typing import TypedDict

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Data structures
# --------------------------------------------------------------------------- #

class KBEntry(TypedDict):
    id: str
    question: str
    keywords: list[str]
    answer: str
    category: str


# --------------------------------------------------------------------------- #
# Tokenization helpers
# --------------------------------------------------------------------------- #

_TOKEN_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)

_STOPWORDS = {
    "the", "is", "are", "a", "an", "and", "or", "what", "how", "why", "when",
    "where", "which", "who", "does", "do", "did", "of", "for", "to", "in",
    "on", "with", "about", "by", "at", "from", "as", "it", "its", "this",
    "that", "be", "been", "being", "have", "has", "had", "will", "would",
    "can", "could", "should", "you", "i", "we", "me",
}


def _tokenize(text: str) -> list[str]:
    """Lowercase alphanumeric tokens, stripping stopwords for scoring but keeping for length."""
    tokens = [t.lower() for t in _TOKEN_RE.findall(text)]
    # Keep tokens that are not pure stopwords for scoring; but allow some stopwords
    # to not over-filter short queries. We filter only if token is in stopwords AND length>2.
    return [t for t in tokens if t not in _STOPWORDS or len(t) <= 2]


def _raw_tokens(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text)]


# --------------------------------------------------------------------------- #
# KnowledgeBase core
# --------------------------------------------------------------------------- #

class KnowledgeBase:
    """Loads knowledge_base.json and performs TF-IDF cosine retrieval."""

    def __init__(self, json_path: Path | str | None = None) -> None:
        if json_path is None:
            # Default: same directory as this file
            json_path = Path(__file__).parent / "knowledge_base.json"
        else:
            json_path = Path(json_path)

        if not json_path.exists():
            raise FileNotFoundError(f"Knowledge base JSON not found: {json_path}")

        with open(json_path, "r", encoding="utf-8") as f:
            raw = json.load(f)

        self.entries: list[KBEntry] = raw  # type: ignore
        logger.info("Loaded %d KB entries from %s", len(self.entries), json_path)

        # Build TF-IDF index
        self._doc_texts: list[str] = []
        for e in self.entries:
            combined = f"{e['question']} {' '.join(e['keywords'])} {e['answer']} {e['category']}"
            self._doc_texts.append(combined)

        self._vocab: dict[str, int] = {}
        self._idf: dict[str, float] = {}
        self._doc_vectors: list[dict[str, float]] = []  # sparse TF-IDF
        self._doc_norms: list[float] = []

        self._build_index()

    def _build_index(self) -> None:
        # Document frequency
        df: dict[str, int] = {}
        tokenized_docs: list[list[str]] = []

        for text in self._doc_texts:
            toks = _tokenize(text)
            tokenized_docs.append(toks)
            seen = set(toks)
            for t in seen:
                df[t] = df.get(t, 0) + 1
            for t in toks:
                if t not in self._vocab:
                    self._vocab[t] = len(self._vocab)

        N = len(tokenized_docs)
        # IDF smoothed
        for term, freq in df.items():
            self._idf[term] = math.log((N + 1) / (freq + 1)) + 1.0

        # TF-IDF vectors
        for toks in tokenized_docs:
            tf: dict[str, int] = {}
            for t in toks:
                tf[t] = tf.get(t, 0) + 1
            vec: dict[str, float] = {}
            # TF log-scaled: 1 + log(tf)
            for term, count in tf.items():
                tf_weight = 1.0 + math.log(count) if count > 0 else 0.0
                vec[term] = tf_weight * self._idf.get(term, 1.0)
            norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
            self._doc_vectors.append(vec)
            self._doc_norms.append(norm)

    def _vectorize_query(self, query: str) -> tuple[dict[str, float], float]:
        toks = _tokenize(query)
        if not toks:
            toks = _raw_tokens(query)
        tf: dict[str, int] = {}
        for t in toks:
            tf[t] = tf.get(t, 0) + 1
        vec: dict[str, float] = {}
        for term, count in tf.items():
            idf = self._idf.get(term, math.log(len(self.entries) + 1))  # unseen terms get high idf but ok
            tf_weight = 1.0 + math.log(count) if count > 0 else 0.0
            vec[term] = tf_weight * idf
        norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
        return vec, norm

    @staticmethod
    def _cosine_similarity(
        q_vec: dict[str, float], q_norm: float,
        d_vec: dict[str, float], d_norm: float
    ) -> float:
        # dot product over intersection
        if q_norm == 0 or d_norm == 0:
            return 0.0
        # iterate smaller
        if len(q_vec) < len(d_vec):
            smaller, larger = q_vec, d_vec
        else:
            smaller, larger = d_vec, q_vec
        dot = 0.0
        for term, weight in smaller.items():
            if term in larger:
                # if smaller is q_vec, weight is q weight; else need to handle both
                # Actually dot needs both vectors values; easiest get from both dicts
                dot += q_vec.get(term, 0.0) * d_vec.get(term, 0.0)
        return dot / (q_norm * d_norm)

    def _keyword_overlap_score(self, query: str, entry: KBEntry) -> float:
        """Simple fuzzy keyword overlap bonus, 0-1."""
        q_tokens = set(_raw_tokens(query))
        if not q_tokens:
            return 0.0
        # entry keywords + question tokens
        e_tokens = set(_raw_tokens(entry["question"]))
        for kw in entry["keywords"]:
            e_tokens.update(_raw_tokens(kw))
        # also include id split by _
        e_tokens.update(entry["id"].split("_"))

        overlap = len(q_tokens & e_tokens)
        # Jaccard-ish
        score = overlap / max(len(q_tokens), 1)
        # Boost exact phrase matches
        q_lower = query.lower()
        if entry["question"].lower() in q_lower or q_lower in entry["question"].lower():
            score += 0.3
        for kw in entry["keywords"]:
            if kw.lower() in q_lower:
                score += 0.15
        return min(score, 1.5)

    def search(self, query: str, top_k: int = 1, threshold: float = 0.15) -> list[tuple[KBEntry, float]]:
        """Return top_k entries with scores above threshold, sorted high->low.

        Scoring: 0.7 * tf-idf cosine + 0.3 * keyword overlap (weighted).
        Falls back to keyword only if tf-idf is very low.
        """
        q_vec, q_norm = self._vectorize_query(query)

        scored: list[tuple[KBEntry, float]] = []
        for idx, entry in enumerate(self.entries):
            d_vec = self._doc_vectors[idx]
            d_norm = self._doc_norms[idx]
            cos_sim = self._cosine_similarity(q_vec, q_norm, d_vec, d_norm)
            kw_score = self._keyword_overlap_score(query, entry)

            # Combined score
            combined = 0.7 * cos_sim + 0.3 * kw_score

            # If query is very short, rely more on keyword overlap
            if len(_tokenize(query)) <= 2:
                combined = 0.4 * cos_sim + 0.6 * kw_score

            scored.append((entry, combined))

        scored.sort(key=lambda x: x[1], reverse=True)

        # Filter threshold
        filtered = [(e, s) for e, s in scored if s >= threshold]
        if not filtered:
            logger.debug("KB search for %r returned no results above threshold %.2f. Top score %.3f", query, threshold, scored[0][1] if scored else 0)
            return []

        return filtered[:top_k]

    def get_best_match(self, query: str, threshold: float = 0.15) -> tuple[KBEntry, float] | None:
        results = self.search(query, top_k=1, threshold=threshold)
        return results[0] if results else None

    def get_all_ids(self) -> list[str]:
        return [e["id"] for e in self.entries]


# Singleton cache for FastAPI dependency
_kb_instance: KnowledgeBase | None = None

def get_knowledge_base() -> KnowledgeBase:
    global _kb_instance
    if _kb_instance is None:
        _kb_instance = KnowledgeBase()
    return _kb_instance
