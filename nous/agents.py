"""
Nous — Multi-Agent Architecture.

Role-based reasoning with Planner, Critic, Executor, and Monitor modes.
"""

from __future__ import annotations

import json
import logging
import os
from nous.utils import get_env
import time
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)


class MultiAgentOrchestrator:
    """Multi-perspective reasoning via role-based LLM calls."""

    def __init__(self):
        self._base_url = os.environ.get(
            "LLM_BASE_URL", "https://montana-wagon-codes-quit.trycloudflare.com/v1"
        )
        self._api_key = os.environ.get("LLM_API_KEY", "dummy")
        self._model = get_env("NOUS_MODEL", "qwen3-coder-next")

    def _call_llm(self, system_prompt: str, user_message: str, max_tokens: int = 2000) -> str:
        """Make an LLM call with a specific role prompt."""
        try:
            from openai import OpenAI
            client = OpenAI(base_url=self._base_url, api_key=self._api_key)
            resp = client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                max_tokens=max_tokens,
                temperature=0.7,
            )
            return resp.choices[0].message.content or ""
        except Exception as e:
            log.error("Multi-agent LLM call failed: %s", e)
            return f"[Error: {e}]"

    def plan_task(self, description: str, context: str = "") -> Dict[str, Any]:
        """Planner mode: Break down a task into steps."""
        system = (
            "You are the Planner agent. Your role is to analyze tasks and create structured "
            "execution plans. Output JSON with keys: 'steps' (list of step objects with "
            "'description', 'tools_needed', 'risk_level'), 'estimated_complexity' (low/medium/high), "
            "'dependencies' (list of external dependencies)."
        )
        user_msg = f"Task: {description}"
        if context:
            user_msg += f"\n\nContext:\n{context}"

        response = self._call_llm(system, user_msg)
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            return {"raw_plan": response, "steps": [{"description": description}]}

    def critique_plan(self, plan: Dict[str, Any]) -> Dict[str, Any]:
        """Critic mode: Review a plan for issues."""
        system = (
            "You are the Critic agent. Review the following plan and identify: "
            "1) Potential failure points, 2) Missing steps, 3) Risk assessment, "
            "4) Suggested improvements. Output JSON with keys: 'issues' (list), "
            "'risk_score' (0-10), 'suggestions' (list), 'verdict' ('approve'/'revise'/'reject')."
        )
        response = self._call_llm(system, json.dumps(plan, indent=2))
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            return {"raw_critique": response, "verdict": "revise"}

    def execute_step(self, step: str, context: str = "") -> str:
        """Executor mode: Provide detailed implementation guidance for a step."""
        system = (
            "You are the Executor agent. Provide precise, actionable implementation "
            "details for the given step. Include exact commands, code snippets, and "
            "file paths. Be concrete, not abstract."
        )
        user_msg = f"Step: {step}"
        if context:
            user_msg += f"\n\nContext:\n{context}"
        return self._call_llm(system, user_msg)

    def monitor_execution(self, execution_log: str) -> Dict[str, Any]:
        """Monitor mode: Analyze execution progress and detect issues."""
        system = (
            "You are the Monitor agent. Analyze the execution log and report: "
            "1) Progress status (on_track/at_risk/blocked), 2) Issues detected, "
            "3) Recommended actions. Output JSON with keys: 'status', 'issues', 'actions'."
        )
        response = self._call_llm(system, execution_log)
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            return {"raw_analysis": response, "status": "unknown"}

    def deliberate(self, question: str, perspectives: List[str] | None = None) -> str:
        """Multi-perspective reasoning on a question."""
        perspectives = perspectives or ["technical", "philosophical", "practical"]

        results = []
        for perspective in perspectives:
            system = (
                f"You are analyzing a question from a {perspective} perspective. "
                f"Provide a focused, insightful analysis from this viewpoint. "
                f"Be concise but thorough."
            )
            response = self._call_llm(system, question, max_tokens=1000)
            results.append(f"### {perspective.title()} Perspective\n{response}")

        # Synthesis
        all_perspectives = "\n\n".join(results)
        synthesis_system = (
            "You are synthesizing multiple perspectives into a coherent conclusion. "
            "Identify agreements, tensions, and arrive at a balanced recommendation."
        )
        synthesis = self._call_llm(synthesis_system, all_perspectives, max_tokens=1500)

        return f"{all_perspectives}\n\n### Synthesis\n{synthesis}"

    def plan_and_critique(self, description: str, context: str = "",
                          max_iterations: int = 2) -> Dict[str, Any]:
        """Full plan-critique loop until approved or max iterations."""
        plan = self.plan_task(description, context)

        for i in range(max_iterations):
            critique = self.critique_plan(plan)
            if critique.get("verdict") == "approve":
                return {"plan": plan, "critique": critique, "iterations": i + 1, "status": "approved"}

            # Revise based on critique
            revision_prompt = (
                f"Original plan:\n{json.dumps(plan, indent=2)}\n\n"
                f"Critique:\n{json.dumps(critique, indent=2)}\n\n"
                f"Revise the plan to address the critique."
            )
            plan = self.plan_task(revision_prompt)

        return {"plan": plan, "critique": critique, "iterations": max_iterations, "status": "max_iterations"}
