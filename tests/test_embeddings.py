"""Test embedding provider with TF-IDF fallback."""

import pytest


def test_embedding_provider_init():
    """EmbeddingProvider should initialize without errors."""
    from nous.embeddings import EmbeddingProvider
    provider = EmbeddingProvider()
    assert provider is not None


def test_tfidf_different_texts():
    """Different texts should produce different embeddings."""
    from nous.embeddings import EmbeddingProvider

    provider = EmbeddingProvider()
    provider._use_api = False

    embeddings = provider.embed([
        "machine learning algorithms",
        "cooking recipes for dinner",
    ])
    assert len(embeddings) == 2

    sim = EmbeddingProvider.cosine_similarity(embeddings[0], embeddings[1])
    # Very different texts should have low similarity
    assert sim < 0.5


def test_tfidf_similar_texts():
    """Similar texts should have higher similarity."""
    from nous.embeddings import EmbeddingProvider

    provider = EmbeddingProvider()
    provider._use_api = False

    embeddings = provider.embed([
        "python programming tutorial",
        "python coding tutorial guide",
        "cooking italian pasta recipe",
    ])

    sim_related = EmbeddingProvider.cosine_similarity(embeddings[0], embeddings[1])
    sim_unrelated = EmbeddingProvider.cosine_similarity(embeddings[0], embeddings[2])

    assert sim_related > sim_unrelated


def test_tfidf_single_text():
    """Single text embedding should work."""
    from nous.embeddings import EmbeddingProvider

    provider = EmbeddingProvider()
    provider._use_api = False

    embeddings = provider.embed(["hello world"])
    assert len(embeddings) == 1
    assert len(embeddings[0]) > 0
    # Should be normalized (L2 norm ~= 1.0)
    import math
    norm = math.sqrt(sum(v * v for v in embeddings[0]))
    assert abs(norm - 1.0) < 0.01


def test_empty_text():
    """Empty text should not crash."""
    from nous.embeddings import EmbeddingProvider

    provider = EmbeddingProvider()
    provider._use_api = False

    embeddings = provider.embed([""])
    assert len(embeddings) == 1
