"""
Nous — Capability Self-Assessment.

Track and assess capabilities across domains over time.
"""

from __future__ import annotations

import json
import logging
import os
from nous.utils import get_env
import pathlib
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List

log = logging.getLogger(__name__)


@dataclass
class CapabilityScore:
    """Assessment of capability in a domain."""
    domain: str = ""
    score: float = 0.0           # 0.0 to 1.0
    confidence: float = 0.0      # How confident in this assessment
    sample_size: int = 0         # Number of tasks assessed
    strengths: List[str] = field(default_factory=list)
    weaknesses: List[str] = field(default_factory=list)
    trend: str = "stable"        # "improving" | "stable" | "declining"
    assessed_at: float = 0.0


class CapabilityTracker:
    """Track capabilities across domains over time."""

    def __init__(self, drive_root: pathlib.Path | None = None):
        root = drive_root or pathlib.Path(get_env("NOUS_DRIVE_ROOT", str(pathlib.Path.home() / ".nous")))
        self._dir = root / "memory" / "capabilities"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._profile_path = self._dir / "profile.json"
        self._history_path = self._dir / "history.jsonl"

    def assess_capability(self, domain: str) -> CapabilityScore:
        """Assess current capability in a domain based on experience data."""
        profile = self._load_profile()

        # Try to get experience data
        try:
            from nous.experience import ExperienceStore
            store = ExperienceStore()
            all_exp = store._load_all()
            domain_exp = [e for e in all_exp if e.domain == domain]
        except Exception:
            domain_exp = []

        if not domain_exp:
            return CapabilityScore(
                domain=domain, score=0.5, confidence=0.1,
                sample_size=0, assessed_at=time.time(),
            )

        successes = sum(1 for e in domain_exp if e.outcome == "success")
        total = len(domain_exp)
        score = successes / total if total > 0 else 0.5
        confidence = min(1.0, total / 20)  # Full confidence at 20+ samples

        # Detect trend from history
        history = self._load_history(domain)
        trend = "stable"
        if len(history) >= 3:
            recent = [h["score"] for h in history[-3:]]
            if all(recent[i] < recent[i + 1] for i in range(len(recent) - 1)):
                trend = "improving"
            elif all(recent[i] > recent[i + 1] for i in range(len(recent) - 1)):
                trend = "declining"

        result = CapabilityScore(
            domain=domain,
            score=score,
            confidence=confidence,
            sample_size=total,
            trend=trend,
            assessed_at=time.time(),
        )

        # Save to profile and history
        profile[domain] = asdict(result)
        self._save_profile(profile)
        self._append_history(result)

        return result

    def get_capability_profile(self) -> Dict[str, Any]:
        """Get full capability profile across all assessed domains."""
        return self._load_profile()

    def track_over_time(self, domain: str = "") -> List[Dict[str, Any]]:
        """Get historical capability assessments."""
        return self._load_history(domain)

    def identify_growth_areas(self) -> List[str]:
        """Identify domains with most room for improvement."""
        profile = self._load_profile()
        if not profile:
            return ["No assessments yet. Complete tasks across domains to build a capability profile."]

        areas = []
        for domain, data in sorted(profile.items(), key=lambda x: x[1].get("score", 0)):
            score = data.get("score", 0)
            if score < 0.7:
                areas.append(f"{domain}: {score:.0%} ({data.get('trend', 'stable')})")

        return areas or ["All assessed domains above 70% — consider exploring new domains."]

    def _load_profile(self) -> Dict[str, Any]:
        if self._profile_path.exists():
            try:
                return json.loads(self._profile_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                return {}
        return {}

    def _save_profile(self, profile: Dict[str, Any]) -> None:
        self._profile_path.write_text(json.dumps(profile, indent=2), encoding="utf-8")

    def _load_history(self, domain: str = "") -> List[Dict[str, Any]]:
        history = []
        if self._history_path.exists():
            for line in self._history_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    if not domain or data.get("domain") == domain:
                        history.append(data)
                except json.JSONDecodeError:
                    continue
        return history

    def _append_history(self, score: CapabilityScore) -> None:
        with open(self._history_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(score), separators=(",", ":")) + "\n")
