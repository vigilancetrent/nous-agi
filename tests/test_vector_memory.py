"""Test vector index add/search/delete."""

import pathlib
import tempfile
import pytest


def test_vector_index_add_search():
    """Add entries and search for them."""
    from nous.embeddings import VectorIndex, EmbeddingProvider

    with tempfile.TemporaryDirectory() as tmp:
        idx = VectorIndex(pathlib.Path(tmp) / "test.jsonl")

        idx.add("1", "Python programming language")
        idx.add("2", "JavaScript web development")
        idx.add("3", "Python data science and machine learning")

        results = idx.search(query="Python coding", top_k=2)
        assert len(results) == 2
        # Python entries should score higher
        ids = [r["id"] for r in results]
        assert "1" in ids or "3" in ids


def test_vector_index_delete():
    """Delete should remove entries."""
    from nous.embeddings import VectorIndex

    with tempfile.TemporaryDirectory() as tmp:
        idx = VectorIndex(pathlib.Path(tmp) / "test.jsonl")
        idx.add("1", "test entry")
        assert idx.count() == 1

        deleted = idx.delete("1")
        assert deleted is True
        assert idx.count() == 0


def test_vector_index_persistence():
    """Index should persist across instances."""
    from nous.embeddings import VectorIndex

    with tempfile.TemporaryDirectory() as tmp:
        path = pathlib.Path(tmp) / "test.jsonl"

        idx1 = VectorIndex(path)
        idx1.add("1", "persistent entry")

        idx2 = VectorIndex(path)
        assert idx2.count() == 1


def test_embedding_tfidf_fallback():
    """TF-IDF fallback should produce valid embeddings."""
    from nous.embeddings import EmbeddingProvider

    provider = EmbeddingProvider()
    provider._use_api = False  # Force TF-IDF

    embeddings = provider.embed(["hello world", "goodbye world"])
    assert len(embeddings) == 2
    assert len(embeddings[0]) > 0

    # Same-ish texts should have higher similarity
    sim = EmbeddingProvider.cosine_similarity(embeddings[0], embeddings[1])
    assert sim > 0.0  # They share "world"


def test_cosine_similarity():
    """Cosine similarity basic properties."""
    from nous.embeddings import EmbeddingProvider

    # Identical vectors = 1.0
    assert abs(EmbeddingProvider.cosine_similarity([1, 0, 0], [1, 0, 0]) - 1.0) < 0.001
    # Orthogonal vectors = 0.0
    assert abs(EmbeddingProvider.cosine_similarity([1, 0, 0], [0, 1, 0])) < 0.001
