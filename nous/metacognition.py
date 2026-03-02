"""
Nous — Meta-Cognitive Loop.

Post-task self-evaluation and reasoning pattern detection.
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
class CognitiveEvaluation:
    """Result of a meta-cognitive self-evaluation."""
    id: str = ""
    task_id: str = ""
    timestamp: float = 0.0
    task_type: str = ""
    quality_score: float = 0.0      # 0.0 to 1.0
    efficiency_score: float = 0.0   # tokens_needed / tokens_used
    reasoning_quality: str = ""     # "strong" | "adequate" | "weak"
    patterns_observed: List[str] = field(default_factory=list)
    improvements: List[str] = field(default_factory=list)
    strategy_effectiveness: str = ""
    tokens_used: int = 0
    rounds_used: int = 0


class MetaCognitiveLoop:
    """Self-evaluation and reasoning pattern analysis."""

    def __init__(self, drive_root: pathlib.Path | None = None):
        root = drive_root or pathlib.Path(get_env("NOUS_DRIVE_ROOT", str(pathlib.Path.home() / ".nous")))
        self._dir = root / "memory" / "metacognition"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._eval_path = self._dir / "evaluations.jsonl"
        self._patterns_path = self._dir / "patterns.json"

    def evaluate_task(self, task_id: str, task_type: str = "",
                      tokens_used: int = 0, rounds_used: int = 0,
                      outcome: str = "success", tools_used: List[str] | None = None) -> CognitiveEvaluation:
        """Evaluate a completed task for self-improvement."""
        eval_id = hashlib.sha256(f"{task_id}:{time.time()}".encode()).hexdigest()[:10]

        # Compute efficiency
        efficiency = min(1.0, 5000 / max(tokens_used, 1))  # Baseline: 5k tokens is "efficient"

        # Detect patterns
        patterns = []
        if rounds_used > 15:
            patterns.append("high_round_count")
        if tokens_used > 50000:
            patterns.append("high_token_usage")
        if tools_used:
            tool_set = set(tools_used)
            if len(tool_set) < 3:
                patterns.append("limited_tool_diversity")
            if "run_shell" in tool_set and len(tool_set) == 1:
                patterns.append("shell_only_approach")

        # Quality assessment
        quality = 0.8 if outcome == "success" else (0.5 if outcome == "partial" else 0.2)

        # Improvements
        improvements = []
        if "high_round_count" in patterns:
            improvements.append("Consider more decisive action to reduce round count")
        if "high_token_usage" in patterns:
            improvements.append("Look for more token-efficient approaches")
        if "limited_tool_diversity" in patterns:
            improvements.append("Explore using a wider range of tools")

        reasoning = "strong" if quality > 0.7 and efficiency > 0.5 else (
            "adequate" if quality > 0.4 else "weak"
        )

        evaluation = CognitiveEvaluation(
            id=eval_id,
            task_id=task_id,
            timestamp=time.time(),
            task_type=task_type,
            quality_score=quality,
            efficiency_score=efficiency,
            reasoning_quality=reasoning,
            patterns_observed=patterns,
            improvements=improvements,
            tokens_used=tokens_used,
            rounds_used=rounds_used,
        )

        # Persist
        with open(self._eval_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(evaluation), separators=(",", ":")) + "\n")

        self._update_patterns(evaluation)
        log.info("Meta-eval %s: quality=%.1f efficiency=%.1f reasoning=%s",
                 eval_id, quality, efficiency, reasoning)
        return evaluation

    def _update_patterns(self, evaluation: CognitiveEvaluation) -> None:
        """Update aggregate pattern statistics."""
        patterns = {}
        if self._patterns_path.exists():
            try:
                patterns = json.loads(self._patterns_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                patterns = {}

        for pattern in evaluation.patterns_observed:
            if pattern not in patterns:
                patterns[pattern] = {"count": 0, "first_seen": evaluation.timestamp}
            patterns[pattern]["count"] += 1
            patterns[pattern]["last_seen"] = evaluation.timestamp

        self._patterns_path.write_text(json.dumps(patterns, indent=2), encoding="utf-8")

    def get_strategy_recommendations(self, task_type: str = "") -> str:
        """Get recommendations based on past evaluations."""
        evals = self._load_evaluations()
        if not evals:
            return "No evaluations yet. Complete some tasks to build meta-cognitive insights."

        # Filter by task type if specified
        relevant = [e for e in evals if not task_type or e.task_type == task_type]
        if not relevant:
            relevant = evals

        recent = relevant[-10:]  # Last 10 evaluations
        avg_quality = sum(e.quality_score for e in recent) / len(recent)
        avg_efficiency = sum(e.efficiency_score for e in recent) / len(recent)

        lines = [f"## Meta-Cognitive Insights\n"]
        lines.append(f"Based on {len(recent)} recent evaluations:")
        lines.append(f"- Average quality: {avg_quality:.1%}")
        lines.append(f"- Average efficiency: {avg_efficiency:.1%}")

        # Aggregate improvements
        all_improvements: Dict[str, int] = {}
        for e in recent:
            for imp in e.improvements:
                all_improvements[imp] = all_improvements.get(imp, 0) + 1

        if all_improvements:
            lines.append("\n**Recurring suggestions:**")
            for imp, count in sorted(all_improvements.items(), key=lambda x: -x[1])[:5]:
                lines.append(f"- ({count}x) {imp}")

        return "\n".join(lines)

    def detect_reasoning_patterns(self) -> Dict[str, Any]:
        """Analyze reasoning patterns across evaluations."""
        patterns = {}
        if self._patterns_path.exists():
            try:
                patterns = json.loads(self._patterns_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                pass
        return patterns

    def _load_evaluations(self) -> List[CognitiveEvaluation]:
        evals = []
        if self._eval_path.exists():
            for line in self._eval_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    evals.append(CognitiveEvaluation(**{
                        k: v for k, v in data.items()
                        if k in CognitiveEvaluation.__dataclass_fields__
                    }))
                except (json.JSONDecodeError, TypeError):
                    continue
        return evals
