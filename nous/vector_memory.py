"""
Nous — Vector Memory.

Semantic search across knowledge, chat messages, and experiences.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from nous.utils import get_env
import pathlib
import time
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)


class VectorMemory:
    """Unified semantic memory across knowledge, chat, and experiences."""

    def __init__(self, drive_root: pathlib.Path | None = None):
        root = drive_root or pathlib.Path(get_env("NOUS_DRIVE_ROOT", str(pathlib.Path.home() / ".nous")))
        self._dir = root / "memory" / "vectors"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._provider = None

    def _get_provider(self):
        if self._provider is None:
            from nous.embeddings import EmbeddingProvider
            self._provider = EmbeddingProvider()
        return self._provider

    def _get_index(self, name: str):
        from nous.embeddings import VectorIndex
        return VectorIndex(self._dir / f"{name}_vectors.jsonl", self._get_provider())

    def index_knowledge(self, topic: str, content: str) -> None:
        """Index a knowledge base entry for semantic search."""
        idx = self._get_index("knowledge")
        entry_id = hashlib.sha256(topic.encode()).hexdigest()[:12]
        idx.add(
            id=entry_id,
            text=f"{topic}: {content[:1500]}",
            metadata={"topic": topic, "source": "knowledge", "indexed_at": time.time()},
        )
        log.debug("Indexed knowledge: %s", topic)

    def index_chat_message(self, message: str, direction: str, timestamp: float | None = None) -> None:
        """Index a chat message for semantic search."""
        idx = self._get_index("chat")
        ts = timestamp or time.time()
        msg_id = hashlib.sha256(f"{message}:{ts}".encode()).hexdigest()[:12]
        idx.add(
            id=msg_id,
            text=message[:1000],
            metadata={"direction": direction, "timestamp": ts, "source": "chat"},
        )

    def index_experience(self, experience_id: str, text: str, metadata: Dict[str, Any] | None = None) -> None:
        """Index an experience for semantic search."""
        idx = self._get_index("experience")
        idx.add(id=experience_id, text=text, metadata={**(metadata or {}), "source": "experience"})

    def search(self, query: str, sources: List[str] | None = None,
               top_k: int = 10) -> List[Dict[str, Any]]:
        """Search across specified sources (default: all)."""
        sources = sources or ["knowledge", "chat", "experience"]
        all_results = []

        for source in sources:
            idx = self._get_index(source)
            results = idx.search(query=query, top_k=top_k)
            for r in results:
                r["source"] = source
            all_results.extend(results)

        # Sort by score across all sources
        all_results.sort(key=lambda x: x.get("score", 0), reverse=True)
        return all_results[:top_k]

    def reindex_all(self, knowledge_dir: pathlib.Path | None = None) -> Dict[str, int]:
        """Reindex all knowledge files."""
        counts = {"knowledge": 0, "chat": 0, "experience": 0}

        if knowledge_dir and knowledge_dir.exists():
            for f in knowledge_dir.glob("*.md"):
                topic = f.stem
                content = f.read_text(encoding="utf-8", errors="replace")[:2000]
                self.index_knowledge(topic, content)
                counts["knowledge"] += 1

        log.info("Reindexed: %s", counts)
        return counts

    def get_stats(self) -> Dict[str, int]:
        """Get counts per source."""
        stats = {}
        for source in ["knowledge", "chat", "experience"]:
            idx = self._get_index(source)
            stats[source] = idx.count()
        return stats
