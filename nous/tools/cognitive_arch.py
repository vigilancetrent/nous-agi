"""
Nous — Cognitive architecture tools.

Prompt analysis, modification, and context configuration.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from nous.tools.registry import ToolContext, ToolEntry


def _get_arch(ctx: ToolContext):
    from nous.cognitive_arch import CognitiveArchitecture
    return CognitiveArchitecture(repo_dir=ctx.repo_dir, drive_root=ctx.drive_root)


async def _analyze_prompt(args: Dict[str, Any], ctx: ToolContext) -> str:
    arch = _get_arch(ctx)
    path = args.get("prompt_path", "")
    result = arch.analyze_prompt_effectiveness(path)
    return json.dumps(result, indent=2)


async def _modify_prompt(args: Dict[str, Any], ctx: ToolContext) -> str:
    arch = _get_arch(ctx)
    action = args.get("action", "propose")

    if action == "propose":
        result = arch.propose_prompt_modification(
            prompt_path=args.get("prompt_path", ""),
            rationale=args.get("rationale", ""),
            changes_description=args.get("changes_description", ""),
        )
        return json.dumps(result, indent=2)
    elif action == "apply":
        return arch.apply_prompt_modification(
            modification_id=args.get("modification_id", ""),
            new_content=args.get("new_content", ""),
        )
    elif action == "rollback":
        return arch.rollback_modification(args.get("modification_id", ""))
    else:
        return json.dumps({"error": f"Unknown action: {action}"})


async def _modify_context_config(args: Dict[str, Any], ctx: ToolContext) -> str:
    arch = _get_arch(ctx)
    changes = args.get("changes", {})
    if not changes:
        config = arch.get_context_config()
        return json.dumps(config, indent=2)
    return arch.modify_context_config(changes)


def get_tools(ctx: ToolContext) -> List[ToolEntry]:
    return [
        ToolEntry("analyze_prompt", {
            "name": "analyze_prompt",
            "description": "Analyze a prompt file for effectiveness indicators.",
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt_path": {"type": "string", "description": "Relative path to prompt file (e.g. 'prompts/SYSTEM.md')"},
                },
                "required": ["prompt_path"],
            },
        }, _analyze_prompt),
        ToolEntry("modify_prompt", {
            "name": "modify_prompt",
            "description": "Propose, apply, or rollback prompt modifications with safety tracking.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["propose", "apply", "rollback"]},
                    "prompt_path": {"type": "string", "description": "For propose: path to prompt file"},
                    "rationale": {"type": "string", "description": "For propose: why this change"},
                    "changes_description": {"type": "string", "description": "For propose: what will change"},
                    "modification_id": {"type": "string", "description": "For apply/rollback: modification ID"},
                    "new_content": {"type": "string", "description": "For apply: new prompt content"},
                },
                "required": ["action"],
            },
        }, _modify_prompt),
        ToolEntry("modify_context_config", {
            "name": "modify_context_config",
            "description": "View or modify context building configuration.",
            "parameters": {
                "type": "object",
                "properties": {
                    "changes": {"type": "object", "description": "Config changes to apply. Empty to view current config."},
                },
            },
        }, _modify_context_config),
    ]
