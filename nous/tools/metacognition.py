"""
Nous — Meta-cognitive tools.

Self-evaluation and reasoning insight tools.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from nous.tools.registry import ToolContext, ToolEntry


def _get_loop(ctx: ToolContext):
    from nous.metacognition import MetaCognitiveLoop
    return MetaCognitiveLoop(drive_root=ctx.drive_root)


async def _self_evaluate(args: Dict[str, Any], ctx: ToolContext) -> str:
    loop = _get_loop(ctx)
    evaluation = loop.evaluate_task(
        task_id=args.get("task_id", "manual"),
        task_type=args.get("task_type", ""),
        tokens_used=args.get("tokens_used", 0),
        rounds_used=args.get("rounds_used", 0),
        outcome=args.get("outcome", "success"),
        tools_used=args.get("tools_used", []),
    )
    return json.dumps({
        "eval_id": evaluation.id,
        "quality": evaluation.quality_score,
        "efficiency": evaluation.efficiency_score,
        "reasoning": evaluation.reasoning_quality,
        "patterns": evaluation.patterns_observed,
        "improvements": evaluation.improvements,
    })


async def _get_reasoning_insights(args: Dict[str, Any], ctx: ToolContext) -> str:
    loop = _get_loop(ctx)
    recommendations = loop.get_strategy_recommendations(args.get("task_type", ""))
    patterns = loop.detect_reasoning_patterns()
    return recommendations + "\n\n**Pattern frequency:**\n" + json.dumps(patterns, indent=2)


def get_tools(ctx: ToolContext) -> List[ToolEntry]:
    return [
        ToolEntry("self_evaluate", {
            "name": "self_evaluate",
            "description": "Evaluate a completed task for meta-cognitive self-improvement.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "Task identifier"},
                    "task_type": {"type": "string", "description": "Type of task"},
                    "tokens_used": {"type": "integer"},
                    "rounds_used": {"type": "integer"},
                    "outcome": {"type": "string", "enum": ["success", "partial", "failure"]},
                    "tools_used": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["task_id"],
            },
        }, _self_evaluate),
        ToolEntry("get_reasoning_insights", {
            "name": "get_reasoning_insights",
            "description": "Get meta-cognitive insights and strategy recommendations.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_type": {"type": "string", "description": "Filter by task type (optional)"},
                },
            },
        }, _get_reasoning_insights),
    ]
