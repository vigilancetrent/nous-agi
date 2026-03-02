"""
Nous — Hierarchical Goal System.

Autonomous goal formation, tracking, and pruning.
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
class Goal:
    """A single goal in the hierarchy."""
    id: str = ""
    title: str = ""
    description: str = ""
    status: str = "active"        # "active" | "completed" | "abandoned" | "blocked"
    priority: int = 5             # 1 (highest) to 10 (lowest)
    parent_id: str = ""           # Empty = top-level goal
    created_at: float = 0.0
    updated_at: float = 0.0
    deadline: float = 0.0         # 0 = no deadline
    progress: float = 0.0         # 0.0 to 1.0
    tags: List[str] = field(default_factory=list)
    notes: str = ""
    success_criteria: str = ""


class GoalTree:
    """Hierarchical goal management with persistence."""

    def __init__(self, drive_root: pathlib.Path | None = None):
        root = drive_root or pathlib.Path(get_env("NOUS_DRIVE_ROOT", str(pathlib.Path.home() / ".nous")))
        self._path = root / "memory" / "goals.json"
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._goals: Dict[str, Goal] = {}
        self._load()

    def _load(self) -> None:
        """Load goals from JSON file."""
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                for gdata in data.get("goals", []):
                    g = Goal(**{k: v for k, v in gdata.items() if k in Goal.__dataclass_fields__})
                    self._goals[g.id] = g
            except (json.JSONDecodeError, TypeError) as e:
                log.warning("Failed to load goals: %s", e)

    def _save(self) -> None:
        """Persist goals to JSON."""
        data = {"goals": [asdict(g) for g in self._goals.values()], "updated_at": time.time()}
        self._path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def add_goal(self, goal: Goal) -> str:
        """Add a new goal. Returns goal ID."""
        if not goal.id:
            goal.id = hashlib.sha256(
                f"{goal.title}:{time.time()}".encode()
            ).hexdigest()[:8]
        goal.created_at = goal.created_at or time.time()
        goal.updated_at = time.time()
        self._goals[goal.id] = goal
        self._save()
        log.info("Goal added: %s \u2014 %s", goal.id, goal.title)
        return goal.id

    def update_goal(self, goal_id: str, **updates) -> Optional[Goal]:
        """Update goal fields. Returns updated goal or None."""
        goal = self._goals.get(goal_id)
        if not goal:
            return None
        for key, value in updates.items():
            if hasattr(goal, key):
                setattr(goal, key, value)
        goal.updated_at = time.time()
        self._save()
        return goal

    def get_goal(self, goal_id: str) -> Optional[Goal]:
        return self._goals.get(goal_id)

    def get_active_goals(self) -> List[Goal]:
        """Get all active goals sorted by priority."""
        active = [g for g in self._goals.values() if g.status == "active"]
        active.sort(key=lambda g: g.priority)
        return active

    def get_children(self, parent_id: str) -> List[Goal]:
        """Get child goals of a parent."""
        return [g for g in self._goals.values() if g.parent_id == parent_id]

    def get_goal_tree(self, max_depth: int = 3) -> str:
        """Format goal tree for context injection."""
        lines = ["## Active Goals\n"]
        top_level = [g for g in self.get_active_goals() if not g.parent_id]

        for goal in top_level[:10]:
            self._format_goal(goal, lines, depth=0, max_depth=max_depth)

        if not top_level:
            lines.append("No active goals set.")

        return "\n".join(lines)

    def _format_goal(self, goal: Goal, lines: List[str], depth: int, max_depth: int) -> None:
        indent = "  " * depth
        progress_bar = f"[{'\u2588' * int(goal.progress * 10)}{'\u2591' * (10 - int(goal.progress * 10))}]"
        lines.append(f"{indent}- **{goal.title}** (P{goal.priority}) {progress_bar} {goal.progress:.0%}")
        if goal.description and depth == 0:
            lines.append(f"{indent}  {goal.description[:100]}")

        if depth < max_depth:
            for child in self.get_children(goal.id):
                if child.status == "active":
                    self._format_goal(child, lines, depth + 1, max_depth)

    def suggest_goals_from_experiences(self, experience_store) -> List[Goal]:
        """Suggest new goals based on past experience patterns."""
        stats = experience_store.get_stats()
        suggestions = []

        # Suggest improving areas with failures
        if stats.get("outcomes", {}).get("failure", 0) > 2:
            suggestions.append(Goal(
                title="Reduce task failure rate",
                description=f"Currently {stats['outcomes'].get('failure', 0)} failures recorded. Analyze patterns and improve.",
                priority=3,
                tags=["meta", "improvement"],
            ))

        return suggestions

    def prune_stale_goals(self, max_age_hours: int = 168) -> List[str]:
        """Prune goals not updated within max_age_hours. Returns pruned IDs."""
        cutoff = time.time() - (max_age_hours * 3600)
        pruned = []
        for gid, goal in list(self._goals.items()):
            if goal.status == "active" and goal.updated_at < cutoff:
                goal.status = "abandoned"
                goal.notes += f"\nAuto-pruned: stale for {max_age_hours}h"
                pruned.append(gid)
        if pruned:
            self._save()
            log.info("Pruned %d stale goals", len(pruned))
        return pruned
