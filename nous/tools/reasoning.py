"""
Nous — Formal reasoning tools.

Structured argument construction and decision analysis.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any, Dict, List

from nous.tools.registry import ToolContext, ToolEntry


def _get_reasoner():
    from nous.reasoning import FormalReasoner
    return FormalReasoner()


async def _formal_argument(args: Dict[str, Any], ctx: ToolContext) -> str:
    reasoner = _get_reasoner()
    claim = args.get("claim", "")
    evidence = args.get("evidence", [])
    argument = reasoner.construct_argument(claim, evidence)
    return json.dumps(asdict(argument), indent=2)


async def _evaluate_argument(args: Dict[str, Any], ctx: ToolContext) -> str:
    reasoner = _get_reasoner()
    from nous.reasoning import Argument
    arg = Argument(
        claim=args.get("claim", ""),
        evidence=args.get("evidence", []),
        warrants=args.get("warrants", []),
        rebuttals=args.get("rebuttals", []),
    )
    result = reasoner.evaluate_argument(arg)
    return json.dumps(result, indent=2)


async def _decision_matrix(args: Dict[str, Any], ctx: ToolContext) -> str:
    reasoner = _get_reasoner()
    options = args.get("options", [])
    criteria = args.get("criteria", [])
    result = reasoner.decision_matrix(options, criteria)
    return json.dumps(result, indent=2, default=str)


def get_tools(ctx: ToolContext) -> List[ToolEntry]:
    return [
        ToolEntry("formal_argument", {
            "name": "formal_argument",
            "description": "Construct a formal Toulmin argument from claim and evidence.",
            "parameters": {
                "type": "object",
                "properties": {
                    "claim": {"type": "string", "description": "The claim to argue"},
                    "evidence": {"type": "array", "items": {"type": "string"}, "description": "Supporting evidence"},
                },
                "required": ["claim", "evidence"],
            },
        }, _formal_argument),
        ToolEntry("evaluate_argument", {
            "name": "evaluate_argument",
            "description": "Evaluate the logical validity and strength of an argument.",
            "parameters": {
                "type": "object",
                "properties": {
                    "claim": {"type": "string"},
                    "evidence": {"type": "array", "items": {"type": "string"}},
                    "warrants": {"type": "array", "items": {"type": "string"}},
                    "rebuttals": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["claim"],
            },
        }, _evaluate_argument),
        ToolEntry("decision_matrix", {
            "name": "decision_matrix",
            "description": "Build a weighted decision matrix to compare options across criteria.",
            "parameters": {
                "type": "object",
                "properties": {
                    "options": {"type": "array", "items": {"type": "string"}, "description": "Options to compare"},
                    "criteria": {"type": "array", "items": {"type": "string"}, "description": "Evaluation criteria"},
                },
                "required": ["options", "criteria"],
            },
        }, _decision_matrix),
    ]
