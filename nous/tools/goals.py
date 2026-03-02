"""
Nous — Goal system tools.

Tools for managing the hierarchical goal tree.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from nous.tools.registry import ToolContext, ToolEntry


def _get_tree(ctx: ToolContext):
    from nous.goals import GoalTree
    return GoalTree(drive_root=ctx.drive_root)


async def _set_goal(ctx: ToolContext, **args) -> str:
    from nous.goals import Goal
    tree = _get_tree(ctx)
    goal = Goal(
        title=args.get("title", ""),
        description=args.get("description", ""),
        priority=args.get("priority", 5),
        parent_id=args.get("parent_id", ""),
        success_criteria=args.get("success_criteria", ""),
        tags=args.get("tags", []),
    )
    goal_id = tree.add_goal(goal)
    return json.dumps({"status": "created", "goal_id": goal_id, "title": goal.title})


async def _list_goals(ctx: ToolContext, **args) -> str:
    tree = _get_tree(ctx)
    return tree.get_goal_tree()


async def _update_goal(ctx: ToolContext, **args) -> str:
    tree = _get_tree(ctx)
    goal_id = args.get("goal_id", "")
    updates = {k: v for k, v in args.items() if k != "goal_id" and v is not None}
    goal = tree.update_goal(goal_id, **updates)
    if goal:
        return json.dumps({"status": "updated", "goal_id": goal_id, "title": goal.title})
    return json.dumps({"error": f"Goal {goal_id} not found"})


async def _suggest_goals(ctx: ToolContext, **args) -> str:
    tree = _get_tree(ctx)
    from nous.experience import ExperienceStore
    store = ExperienceStore(drive_root=ctx.drive_root)
    suggestions = tree.suggest_goals_from_experiences(store)
    return json.dumps({"suggestions": [{"title": g.title, "description": g.description} for g in suggestions]})


def get_tools(ctx: ToolContext) -> List[ToolEntry]:
    return [
        ToolEntry("set_goal", {
            "name": "set_goal",
            "description": "Create a new goal in the goal hierarchy.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Goal title"},
                    "description": {"type": "string", "description": "Detailed description"},
                    "priority": {"type": "integer", "description": "1 (highest) to 10 (lowest), default 5"},
                    "parent_id": {"type": "string", "description": "Parent goal ID for sub-goals"},
                    "success_criteria": {"type": "string", "description": "How to know when this is done"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["title"],
            },
        }, _set_goal),
        ToolEntry("list_goals", {
            "name": "list_goals",
            "description": "Show the current goal tree with progress indicators.",
            "parameters": {"type": "object", "properties": {}},
        }, _list_goals),
        ToolEntry("update_goal", {
            "name": "update_goal",
            "description": "Update a goal's status, progress, or other fields.",
            "parameters": {
                "type": "object",
                "properties": {
                    "goal_id": {"type": "string", "description": "Goal ID to update"},
                    "status": {"type": "string", "enum": ["active", "completed", "abandoned", "blocked"]},
                    "progress": {"type": "number", "description": "0.0 to 1.0"},
                    "notes": {"type": "string", "description": "Additional notes"},
                    "priority": {"type": "integer"},
                },
                "required": ["goal_id"],
            },
        }, _update_goal),
        ToolEntry("suggest_goals", {
            "name": "suggest_goals",
            "description": "Get AI-suggested goals based on past experience patterns.",
            "parameters": {"type": "object", "properties": {}},
        }, _suggest_goals),
    ]
