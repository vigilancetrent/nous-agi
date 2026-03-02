"""
Nous — Predictive Modeling.

Analyze owner patterns and predict needs and failure modes.
"""

from __future__ import annotations

import json
import logging
import os
from nous.utils import get_env
import pathlib
import time
from collections import Counter
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)


class PredictiveModel:
    """Predict owner needs and failure modes from patterns."""

    def __init__(self, drive_root: pathlib.Path | None = None):
        root = drive_root or pathlib.Path(get_env("NOUS_DRIVE_ROOT", str(pathlib.Path.home() / ".nous")))
        self._dir = root / "memory" / "predictions"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._patterns_path = self._dir / "owner_patterns.json"
        self._predictions_path = self._dir / "predictions.jsonl"

    def analyze_owner_patterns(self, chat_log_path: pathlib.Path | None = None) -> Dict[str, Any]:
        """Analyze owner interaction patterns from chat history."""
        patterns = {
            "message_times": [],
            "common_topics": Counter(),
            "task_types": Counter(),
            "avg_response_length": 0,
            "interaction_frequency": "unknown",
        }

        # Try to load chat history
        if chat_log_path and chat_log_path.exists():
            try:
                lines = chat_log_path.read_text(encoding="utf-8", errors="replace").splitlines()
                msg_count = 0
                total_length = 0
                for line in lines[-500:]:  # Last 500 entries
                    try:
                        entry = json.loads(line.strip())
                        if entry.get("direction") == "in":
                            msg_count += 1
                            text = entry.get("text", "")
                            total_length += len(text)

                            # Time analysis
                            ts = entry.get("timestamp")
                            if ts:
                                import datetime
                                dt = datetime.datetime.fromtimestamp(ts)
                                patterns["message_times"].append(dt.hour)

                            # Topic detection (simple keyword matching)
                            text_lower = text.lower()
                            for keyword in ["bug", "fix", "feature", "review", "deploy", "test", "help"]:
                                if keyword in text_lower:
                                    patterns["common_topics"][keyword] += 1
                    except (json.JSONDecodeError, TypeError):
                        continue

                if msg_count > 0:
                    patterns["avg_response_length"] = total_length // msg_count
                patterns["total_messages"] = msg_count
            except Exception as e:
                log.warning("Failed to analyze chat log: %s", e)

        # Convert Counters to dicts for JSON serialization
        result = {
            "common_topics": dict(patterns["common_topics"].most_common(10)),
            "task_types": dict(patterns["task_types"].most_common(10)),
            "avg_message_length": patterns["avg_response_length"],
            "active_hours": self._get_active_hours(patterns["message_times"]),
            "analyzed_at": time.time(),
        }

        self._patterns_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
        return result

    def _get_active_hours(self, hours: List[int]) -> Dict[str, Any]:
        """Determine most active hours from message timestamps."""
        if not hours:
            return {"peak_hours": [], "timezone_guess": "unknown"}
        hour_counts = Counter(hours)
        peak = hour_counts.most_common(3)
        return {
            "peak_hours": [h for h, _ in peak],
            "distribution": dict(hour_counts),
        }

    def predict_next_need(self) -> Optional[str]:
        """Predict what the owner might need next based on patterns."""
        if not self._patterns_path.exists():
            return None

        try:
            patterns = json.loads(self._patterns_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None

        topics = patterns.get("common_topics", {})
        if not topics:
            return None

        # Simple prediction: most common topic is likely next need
        top_topic = max(topics, key=topics.get) if topics else None
        if top_topic:
            return f"Based on interaction patterns, owner frequently asks about '{top_topic}'. Consider proactively preparing for this."
        return None

    def predict_failure_modes(self, planned_action: str) -> List[Dict[str, Any]]:
        """Predict potential failure modes for a planned action."""
        failures = []

        action_lower = planned_action.lower()

        # Pattern-based failure prediction
        risk_patterns = {
            "git push": {"risk": "merge conflict", "mitigation": "Pull and rebase first", "severity": "medium"},
            "delete": {"risk": "data loss", "mitigation": "Create backup before deletion", "severity": "high"},
            "restart": {"risk": "interrupted tasks", "mitigation": "Ensure all tasks are saved", "severity": "medium"},
            "install": {"risk": "dependency conflict", "mitigation": "Check version compatibility", "severity": "low"},
            "modify": {"risk": "breaking change", "mitigation": "Run tests after modification", "severity": "medium"},
            "deploy": {"risk": "deployment failure", "mitigation": "Test in staging first", "severity": "high"},
            "api": {"risk": "rate limiting", "mitigation": "Implement retry with backoff", "severity": "low"},
            "shell": {"risk": "command injection", "mitigation": "Validate and sanitize inputs", "severity": "high"},
        }

        for pattern, info in risk_patterns.items():
            if pattern in action_lower:
                failures.append({
                    "predicted_failure": info["risk"],
                    "severity": info["severity"],
                    "mitigation": info["mitigation"],
                    "trigger": pattern,
                })

        # Record prediction
        with open(self._predictions_path, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "action": planned_action[:200],
                "predictions": failures,
                "timestamp": time.time(),
            }, separators=(",", ":")) + "\n")

        return failures
