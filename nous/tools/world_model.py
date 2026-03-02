"""
Nous — World model tools.

Codebase dependency analysis and impact prediction.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from nous.tools.registry import ToolContext, ToolEntry


def _get_model(ctx: ToolContext):
    from nous.world_model import WorldModel
    return WorldModel(repo_dir=ctx.repo_dir, drive_root=ctx.drive_root)


async def _analyze_impact(args: Dict[str, Any], ctx: ToolContext) -> str:
    model = _get_model(ctx)
    changed = args.get("changed_files", [])
    affected = model.predict_impact(changed)
    return json.dumps({"changed": changed, "affected": affected, "total_affected": len(affected)})


async def _get_dependency_map(args: Dict[str, Any], ctx: ToolContext) -> str:
    model = _get_model(ctx)
    module = args.get("module", "")
    if module:
        return model.get_module_context(module)
    return json.dumps(model.get_summary(), indent=2, default=str)


async def _rebuild_world_model(args: Dict[str, Any], ctx: ToolContext) -> str:
    model = _get_model(ctx)
    result = model.build_dependency_graph()
    return json.dumps({"status": "rebuilt", **result})


def get_tools(ctx: ToolContext) -> List[ToolEntry]:
    return [
        ToolEntry("analyze_impact", {
            "name": "analyze_impact",
            "description": "Predict which files are affected by changes to given files.",
            "parameters": {
                "type": "object",
                "properties": {
                    "changed_files": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of changed file paths (relative to repo root)",
                    },
                },
                "required": ["changed_files"],
            },
        }, _analyze_impact),
        ToolEntry("get_dependency_map", {
            "name": "get_dependency_map",
            "description": "Get dependency information for a module or overall summary.",
            "parameters": {
                "type": "object",
                "properties": {
                    "module": {"type": "string", "description": "Module path (e.g. 'nous/agent.py'). Empty for summary."},
                },
            },
        }, _get_dependency_map),
        ToolEntry("rebuild_world_model", {
            "name": "rebuild_world_model",
            "description": "Rebuild the codebase dependency graph from AST analysis.",
            "parameters": {"type": "object", "properties": {}},
        }, _rebuild_world_model),
    ]
