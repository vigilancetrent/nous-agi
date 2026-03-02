"""
Nous — Formal Reasoning.

Structured argument construction, evaluation, and decision matrices.
"""

from __future__ import annotations

import json
import logging
import os
from nous.utils import get_env
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List

log = logging.getLogger(__name__)


@dataclass
class Argument:
    """A structured formal argument."""
    id: str = ""
    claim: str = ""
    evidence: List[str] = field(default_factory=list)
    warrants: List[str] = field(default_factory=list)   # Why evidence supports claim
    rebuttals: List[str] = field(default_factory=list)   # Counter-arguments
    qualifiers: List[str] = field(default_factory=list)  # Conditions/limitations
    strength: float = 0.0  # 0.0 to 1.0
    timestamp: float = 0.0


class FormalReasoner:
    """Structured reasoning and argument evaluation."""

    def __init__(self):
        self._model = get_env("NOUS_MODEL", "qwen3-coder-next")
        self._base_url = os.environ.get(
            "LLM_BASE_URL", "https://montana-wagon-codes-quit.trycloudflare.com/v1"
        )
        self._api_key = os.environ.get("LLM_API_KEY", "dummy")

    def _call_llm(self, system: str, user: str, max_tokens: int = 1500) -> str:
        try:
            from openai import OpenAI
            client = OpenAI(base_url=self._base_url, api_key=self._api_key)
            resp = client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                max_tokens=max_tokens,
                temperature=0.3,
            )
            return resp.choices[0].message.content or ""
        except Exception as e:
            return f"[Reasoning error: {e}]"

    def construct_argument(self, claim: str, evidence: List[str]) -> Argument:
        """Construct a formal argument from claim and evidence."""
        import hashlib

        system = (
            "You are a formal reasoning engine. Given a claim and evidence, construct a "
            "Toulmin argument model. Output JSON with: 'warrants' (list of strings explaining "
            "why evidence supports claim), 'rebuttals' (list of counter-arguments), "
            "'qualifiers' (conditions/limitations), 'strength' (0.0-1.0)."
        )
        user = f"Claim: {claim}\nEvidence:\n" + "\n".join(f"- {e}" for e in evidence)

        response = self._call_llm(system, user)
        try:
            data = json.loads(response)
        except json.JSONDecodeError:
            data = {"warrants": [], "rebuttals": [], "qualifiers": [], "strength": 0.5}

        return Argument(
            id=hashlib.sha256(claim.encode()).hexdigest()[:8],
            claim=claim,
            evidence=evidence,
            warrants=data.get("warrants", []),
            rebuttals=data.get("rebuttals", []),
            qualifiers=data.get("qualifiers", []),
            strength=data.get("strength", 0.5),
            timestamp=time.time(),
        )

    def evaluate_argument(self, argument: Argument) -> Dict[str, Any]:
        """Evaluate the strength and validity of an argument."""
        system = (
            "Evaluate this formal argument. Check: 1) Evidence sufficiency, "
            "2) Warrant validity, 3) Rebuttal strength, 4) Overall soundness. "
            "Output JSON with: 'validity' ('valid'/'weak'/'invalid'), "
            "'evidence_quality' (0-1), 'logical_coherence' (0-1), 'overall_score' (0-1), "
            "'critique' (string)."
        )
        response = self._call_llm(system, json.dumps(asdict(argument), indent=2))
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            return {"raw_evaluation": response, "validity": "unknown"}

    def dialectic(self, thesis: str, antithesis: str) -> str:
        """Hegelian dialectic: thesis + antithesis -> synthesis."""
        system = (
            "You are performing Hegelian dialectic reasoning. Given a thesis and antithesis, "
            "produce a synthesis that: 1) Acknowledges valid points in both, "
            "2) Resolves the contradiction, 3) Produces a higher-order understanding. "
            "Format: ## Thesis Analysis\n... ## Antithesis Analysis\n... ## Synthesis\n..."
        )
        user = f"Thesis: {thesis}\n\nAntithesis: {antithesis}"
        return self._call_llm(system, user, max_tokens=2000)

    def decision_matrix(self, options: List[str], criteria: List[str]) -> Dict[str, Any]:
        """Build a weighted decision matrix for comparing options."""
        system = (
            "Build a decision matrix. For each option, score it 1-10 on each criterion. "
            "Also assign a weight (1-10) to each criterion based on importance. "
            "Output JSON with: 'weights' (dict of criterion:weight), "
            "'scores' (dict of option:dict of criterion:score), "
            "'totals' (dict of option:weighted_total), 'recommendation' (string)."
        )
        user = f"Options: {', '.join(options)}\nCriteria: {', '.join(criteria)}"

        response = self._call_llm(system, user)
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            return {"raw_matrix": response, "options": options, "criteria": criteria}
