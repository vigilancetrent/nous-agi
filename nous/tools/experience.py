"""
Nous — Experience store tools.

Tools for recording, searching, and analyzing past task experiences.
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, List

from nous.tools.registry import ToolContext, ToolEntry


def _get_store(ctx: ToolContext):
    from nous.experience import ExperienceStore
    return ExperienceStore(drive_root=ctx.drive_root)


def _record_experience(ctx: ToolContext, **args) -> str:
    from nous.experience import Experience
    store = _get_store(ctx)
    exp = Experience(
        task_description=args.get("task_description", ""),
        task_type=args.get("task_type", "general"),
        approach=args.get("approach", ""),
        outcome=args.get("outcome", "success"),
        outcome_details=args.get("outcome_details", ""),
        lessons_learned=args.get("lessons_learned", ""),
        domain=args.get("domain", "general"),
        tags=args.get("tags", []),
        tokens_used=args.get("tokens_used", 0),
        duration_sec=args.get("duration_sec", 0),
        timestamp=time.time(),
    )
    exp_id = store.record(exp)
    return json.dumps({"status": "recorded", "experience_id": exp_id})


def _search_experiences(ctx: ToolContext, **args) -> str:
    store = _get_store(ctx)
    query = args.get("query", "")
    top_k = args.get("top_k", 5)
    experiences = store.search(query, top_k=top_k)
    results = []
    for exp in experiences:
        results.append({
            "id": exp.id,
            "type": exp.task_type,
            "description": exp.task_description[:200],
            "outcome": exp.outcome,
            "approach": exp.approach[:200],
            "lessons": exp.lessons_learned[:200],
        })
    return json.dumps({"results": results, "count": len(results)})


def _get_strategies(ctx: ToolContext, **args) -> str:
    store = _get_store(ctx)
    task = args.get("task_description", "")
    strategies = store.get_relevant_strategies(task)
    return strategies


def get_tools(ctx: ToolContext) -> List[ToolEntry]:
    return [
        ToolEntry("record_experience", {
            "name": "record_experience",
            "description": "Record a task experience for future learning. Include what worked and lessons learned.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_description": {"type": "string", "description": "What the task was"},
                    "task_type": {"type": "string", "description": "Type: evolution, chat, review, debug, research"},
                    "approach": {"type": "string", "description": "Strategy/approach used"},
                    "outcome": {"type": "string", "enum": ["success", "partial", "failure"]},
                    "outcome_details": {"type": "string", "description": "What happened"},
                    "lessons_learned": {"type": "string", "description": "Key takeaways"},
                    "domain": {"type": "string", "description": "Domain: code, research, communication"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["task_description", "outcome"],
            },
        }, _record_experience),
        ToolEntry("search_experiences", {
            "name": "search_experiences",
            "description": "Search past experiences for relevant strategies and lessons.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "What to search for"},
                    "top_k": {"type": "integer", "description": "Number of results (default 5)"},
                },
                "required": ["query"],
            },
        }, _search_experiences),
        ToolEntry("get_strategies", {
            "name": "get_strategies",
            "description": "Get relevant strategies from past experiences for a task.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_description": {"type": "string", "description": "Description of current task"},
                },
                "required": ["task_description"],
            },
        }, _get_strategies),
    ]
