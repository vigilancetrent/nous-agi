"""
Nous — Experience Store.

Records task outcomes for learning from past approaches.
Includes cross-domain strategy extraction (Transfer Learning).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from nous.utils import get_env
import pathlib
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)


@dataclass
class Experience:
    """A recorded task experience."""
    id: str = ""
    timestamp: float = 0.0
    task_description: str = ""
    task_type: str = ""           # "evolution", "chat", "review", "debug", etc.
    approach: str = ""            # Strategy used
    outcome: str = ""             # "success" | "partial" | "failure"
    outcome_details: str = ""     # What happened
    tokens_used: int = 0
    cost: float = 0.0
    duration_sec: float = 0.0
    tools_used: List[str] = field(default_factory=list)
    lessons_learned: str = ""     # Post-hoc reflection
    domain: str = ""              # "code", "research", "communication", etc.
    tags: List[str] = field(default_factory=list)


class ExperienceStore:
    """Persistent experience recording and retrieval."""

    def __init__(self, drive_root: pathlib.Path | None = None):
        root = drive_root or pathlib.Path(get_env("NOUS_DRIVE_ROOT", str(pathlib.Path.home() / ".nous")))
        self._dir = root / "memory" / "experiences"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._index_path = self._dir / "experience_index.jsonl"
        self._provider = None

    def _get_provider(self):
        if self._provider is None:
            from nous.embeddings import EmbeddingProvider
            self._provider = EmbeddingProvider()
        return self._provider

    def _get_index(self):
        from nous.embeddings import VectorIndex
        return VectorIndex(self._dir / "experience_vectors.jsonl", self._get_provider())

    def record(self, experience: Experience) -> str:
        """Record a new experience. Returns experience ID."""
        if not experience.id:
            experience.id = hashlib.sha256(
                f"{experience.task_description}:{experience.timestamp or time.time()}".encode()
            ).hexdigest()[:12]
        if not experience.timestamp:
            experience.timestamp = time.time()

        # Append to JSONL log
        with open(self._index_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(experience), separators=(",", ":")) + "\n")

        # Index for vector search
        search_text = f"{experience.task_type}: {experience.task_description}\n{experience.approach}\n{experience.lessons_learned}"
        idx = self._get_index()
        idx.add(
            id=experience.id,
            text=search_text,
            metadata={"outcome": experience.outcome, "domain": experience.domain, "type": experience.task_type},
        )

        log.info("Recorded experience %s: %s (%s)", experience.id, experience.task_type, experience.outcome)
        return experience.id

    def search(self, query: str, top_k: int = 5) -> List[Experience]:
        """Search for relevant past experiences."""
        idx = self._get_index()
        results = idx.search(query=query, top_k=top_k)

        experiences = []
        # Load full experiences from JSONL
        all_exp = self._load_all()
        exp_map = {e.id: e for e in all_exp}

        for r in results:
            exp = exp_map.get(r["id"])
            if exp:
                experiences.append(exp)
        return experiences

    def _load_all(self) -> List[Experience]:
        """Load all experiences from JSONL."""
        experiences = []
        if self._index_path.exists():
            for line in self._index_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    experiences.append(Experience(**{
                        k: v for k, v in data.items()
                        if k in Experience.__dataclass_fields__
                    }))
                except (json.JSONDecodeError, TypeError):
                    continue
        return experiences

    def get_relevant_strategies(self, task_description: str, top_k: int = 3) -> str:
        """Get formatted relevant strategies for a task description."""
        experiences = self.search(task_description, top_k=top_k)
        if not experiences:
            return "No relevant past experiences found."

        lines = ["## Relevant Past Experiences\n"]
        for exp in experiences:
            lines.append(f"**{exp.task_type}** ({exp.outcome}): {exp.task_description[:100]}")
            if exp.approach:
                lines.append(f"  Approach: {exp.approach[:200]}")
            if exp.lessons_learned:
                lines.append(f"  Lesson: {exp.lessons_learned[:200]}")
            lines.append("")
        return "\n".join(lines)

    def extract_cross_domain_strategies(self, source_domain: str, target_domain: str,
                                          top_k: int = 5) -> List[str]:
        """Extract strategies from source domain applicable to target domain (Transfer Learning)."""
        all_exp = self._load_all()
        source_exps = [e for e in all_exp if e.domain == source_domain and e.outcome == "success"]

        strategies = []
        for exp in source_exps[-top_k:]:
            if exp.lessons_learned:
                strategies.append(
                    f"[From {source_domain}\u2192{target_domain}] {exp.lessons_learned}"
                )
        return strategies

    def get_stats(self) -> Dict[str, Any]:
        """Get experience store statistics."""
        all_exp = self._load_all()
        if not all_exp:
            return {"total": 0}

        outcomes = {}
        domains = {}
        for exp in all_exp:
            outcomes[exp.outcome] = outcomes.get(exp.outcome, 0) + 1
            domains[exp.domain] = domains.get(exp.domain, 0) + 1

        return {
            "total": len(all_exp),
            "outcomes": outcomes,
            "domains": domains,
            "total_tokens": sum(e.tokens_used for e in all_exp),
        }
