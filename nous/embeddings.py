"""
Nous — Embedding and vector search infrastructure.

Shared by experience store, vector memory, goal suggestions.
Falls back to TF-IDF bag-of-words if embedding endpoint unavailable.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import pathlib
import re
from collections import Counter
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Embedding provider
# ---------------------------------------------------------------------------

class EmbeddingProvider:
    """Generate embeddings via LLM endpoint or TF-IDF fallback."""

    def __init__(self, base_url: str | None = None, api_key: str | None = None):
        self._base_url = base_url or os.environ.get(
            "LLM_BASE_URL", "https://montana-wagon-codes-quit.trycloudflare.com/v1"
        )
        self._api_key = api_key or os.environ.get("LLM_API_KEY", "dummy")
        self._use_api = True
        self._idf: Dict[str, float] = {}
        self._vocab: List[str] = []

    def embed(self, texts: List[str]) -> List[List[float]]:
        """Embed a list of texts. Returns list of embedding vectors."""
        if self._use_api:
            try:
                return self._embed_api(texts)
            except Exception as e:
                log.warning("Embedding API failed (%s), falling back to TF-IDF", e)
                self._use_api = False
        return self._embed_tfidf(texts)

    def _embed_api(self, texts: List[str]) -> List[List[float]]:
        """Call the /embeddings endpoint."""
        import requests
        resp = requests.post(
            f"{self._base_url}/embeddings",
            headers={"Authorization": f"Bearer {self._api_key}"},
            json={"input": texts, "model": "text-embedding"},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        return [item["embedding"] for item in data["data"]]

    def _tokenize(self, text: str) -> List[str]:
        """Simple whitespace + lowering tokenizer."""
        return re.findall(r'\b\w+\b', text.lower())

    def _embed_tfidf(self, texts: List[str]) -> List[List[float]]:
        """Bag-of-words TF-IDF fallback (no external deps)."""
        all_tokens = [self._tokenize(t) for t in texts]

        # Build vocabulary from these texts if needed
        vocab_set: set[str] = set()
        for tokens in all_tokens:
            vocab_set.update(tokens)
        vocab = sorted(vocab_set)
        vocab_idx = {w: i for i, w in enumerate(vocab)}

        n_docs = len(texts)
        # Document frequency
        df: Counter[str] = Counter()
        for tokens in all_tokens:
            df.update(set(tokens))

        embeddings = []
        for tokens in all_tokens:
            tf = Counter(tokens)
            vec = [0.0] * len(vocab)
            for word, count in tf.items():
                idx = vocab_idx[word]
                idf = math.log((n_docs + 1) / (df[word] + 1)) + 1
                vec[idx] = count * idf
            # L2 normalize
            norm = math.sqrt(sum(v * v for v in vec)) or 1.0
            vec = [v / norm for v in vec]
            embeddings.append(vec)

        return embeddings

    @staticmethod
    def cosine_similarity(a: List[float], b: List[float]) -> float:
        """Compute cosine similarity between two vectors."""
        if len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a)) or 1.0
        norm_b = math.sqrt(sum(x * x for x in b)) or 1.0
        return dot / (norm_a * norm_b)


# ---------------------------------------------------------------------------
# JSONL-backed vector index
# ---------------------------------------------------------------------------

class VectorIndex:
    """Persistent JSONL-backed vector store with brute-force cosine search."""

    def __init__(self, path: pathlib.Path, provider: EmbeddingProvider | None = None):
        self._path = path
        self._provider = provider or EmbeddingProvider()
        self._entries: List[Dict[str, Any]] = []
        self._load()

    def _load(self) -> None:
        """Load entries from JSONL file."""
        self._entries = []
        if self._path.exists():
            for line in self._path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line:
                    try:
                        self._entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue

    def _save(self) -> None:
        """Persist all entries to JSONL."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "w", encoding="utf-8") as f:
            for entry in self._entries:
                f.write(json.dumps(entry, separators=(",", ":")) + "\n")

    def add(self, id: str, text: str, metadata: Dict[str, Any] | None = None,
            embedding: List[float] | None = None) -> None:
        """Add an entry to the index."""
        if embedding is None:
            embedding = self._provider.embed([text])[0]
        entry = {
            "id": id,
            "text": text[:2000],  # Truncate for storage
            "embedding": embedding,
            "metadata": metadata or {},
        }
        # Remove existing entry with same id
        self._entries = [e for e in self._entries if e["id"] != id]
        self._entries.append(entry)
        self._save()

    def search(self, query: str | None = None, query_embedding: List[float] | None = None,
               top_k: int = 5, filter_fn=None) -> List[Dict[str, Any]]:
        """Search for similar entries. Returns list of dicts with score."""
        if query_embedding is None and query is not None:
            query_embedding = self._provider.embed([query])[0]
        if query_embedding is None:
            return []

        results = []
        for entry in self._entries:
            if filter_fn and not filter_fn(entry):
                continue
            score = EmbeddingProvider.cosine_similarity(query_embedding, entry["embedding"])
            results.append({**entry, "score": score})

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]

    def delete(self, id: str) -> bool:
        """Remove an entry by id."""
        before = len(self._entries)
        self._entries = [e for e in self._entries if e["id"] != id]
        if len(self._entries) < before:
            self._save()
            return True
        return False

    def count(self) -> int:
        return len(self._entries)

    def clear(self) -> None:
        self._entries = []
        self._save()
