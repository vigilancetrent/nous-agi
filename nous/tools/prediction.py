"""
Nous — Predictive modeling tools.

Owner pattern analysis and failure prediction.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from nous.tools.registry import ToolContext, ToolEntry


def _get_model(ctx: ToolContext):
    from nous.prediction import PredictiveModel
    return PredictiveModel(drive_root=ctx.drive_root)


async def _predict_failures(ctx: ToolContext, **args) -> str:
    model = _get_model(ctx)
    action = args.get("planned_action", "")
    failures = model.predict_failure_modes(action)
    if not failures:
        return json.dumps({"status": "no_risks_detected", "action": action})
    return json.dumps({"action": action, "risks": failures, "count": len(failures)})


async def _owner_patterns(ctx: ToolContext, **args) -> str:
    model = _get_model(ctx)
    chat_log = ctx.drive_root / "logs" / "chat.jsonl" if ctx.drive_root else None
    patterns = model.analyze_owner_patterns(chat_log)
    prediction = model.predict_next_need()
    result = {"patterns": patterns}
    if prediction:
        result["prediction"] = prediction
    return json.dumps(result, indent=2, default=str)


def get_tools(ctx: ToolContext) -> List[ToolEntry]:
    return [
        ToolEntry("predict_failures", {
            "name": "predict_failures",
            "description": "Predict potential failure modes for a planned action.",
            "parameters": {
                "type": "object",
                "properties": {
                    "planned_action": {"type": "string", "description": "What you plan to do"},
                },
                "required": ["planned_action"],
            },
        }, _predict_failures),
        ToolEntry("owner_patterns", {
            "name": "owner_patterns",
            "description": "Analyze owner interaction patterns and predict next needs.",
            "parameters": {"type": "object", "properties": {}},
        }, _owner_patterns),
    ]