"""
Nous — Multi-agent reasoning tools.

Tools for multi-perspective deliberation and plan-critique loops.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from nous.tools.registry import ToolContext, ToolEntry


def _get_orchestrator():
    from nous.agents import MultiAgentOrchestrator
    return MultiAgentOrchestrator()


async def _deliberate(args: Dict[str, Any], ctx: ToolContext) -> str:
    orch = _get_orchestrator()
    question = args.get("question", "")
    perspectives = args.get("perspectives", None)
    result = orch.deliberate(question, perspectives)
    return result


async def _plan_and_critique(args: Dict[str, Any], ctx: ToolContext) -> str:
    orch = _get_orchestrator()
    description = args.get("description", "")
    context = args.get("context", "")
    result = orch.plan_and_critique(description, context)
    return json.dumps(result, indent=2, default=str)


def get_tools(ctx: ToolContext) -> List[ToolEntry]:
    return [
        ToolEntry("deliberate", {
            "name": "deliberate",
            "description": "Multi-perspective reasoning on a question. Gets technical, philosophical, and practical viewpoints then synthesizes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "Question to deliberate on"},
                    "perspectives": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Custom perspectives (default: technical, philosophical, practical)",
                    },
                },
                "required": ["question"],
            },
        }, _deliberate),
        ToolEntry("plan_and_critique", {
            "name": "plan_and_critique",
            "description": "Create a plan and iteratively critique/refine it until approved.",
            "parameters": {
                "type": "object",
                "properties": {
                    "description": {"type": "string", "description": "Task to plan"},
                    "context": {"type": "string", "description": "Additional context"},
                },
                "required": ["description"],
            },
        }, _plan_and_critique),
    ]
