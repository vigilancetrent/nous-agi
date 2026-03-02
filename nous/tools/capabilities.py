"""
Nous — Capability assessment tools.

Self-assessment and growth tracking.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from nous.tools.registry import ToolContext, ToolEntry


def _get_tracker(ctx: ToolContext):
    from nous.capabilities import CapabilityTracker
    return CapabilityTracker(drive_root=ctx.drive_root)


async def _assess_capabilities(args: Dict[str, Any], ctx: ToolContext) -> str:
    tracker = _get_tracker(ctx)
    domain = args.get("domain", "general")
    score = tracker.assess_capability(domain)
    return json.dumps({
        "domain": score.domain,
        "score": f"{score.score:.0%}",
        "confidence": f"{score.confidence:.0%}",
        "trend": score.trend,
        "sample_size": score.sample_size,
    })


async def _capability_profile(args: Dict[str, Any], ctx: ToolContext) -> str:
    tracker = _get_tracker(ctx)
    profile = tracker.get_capability_profile()
    growth = tracker.identify_growth_areas()

    lines = ["## Capability Profile\n"]
    for domain, data in sorted(profile.items(), key=lambda x: -x[1].get("score", 0)):
        score = data.get("score", 0)
        trend_icon = {"improving": "↑", "declining": "↓", "stable": "→"}.get(data.get("trend", ""), "→")
        lines.append(f"- **{domain}**: {score:.0%} {trend_icon} (n={data.get('sample_size', 0)})")

    if growth:
        lines.append("\n**Growth Areas:**")
        for area in growth:
            lines.append(f"- {area}")

    return "\n".join(lines)


def get_tools(ctx: ToolContext) -> List[ToolEntry]:
    return [
        ToolEntry("assess_capabilities", {
            "name": "assess_capabilities",
            "description": "Assess current capability level in a specific domain.",
            "parameters": {
                "type": "object",
                "properties": {
                    "domain": {"type": "string", "description": "Domain to assess (e.g. code, research, communication)"},
                },
                "required": ["domain"],
            },
        }, _assess_capabilities),
        ToolEntry("capability_profile", {
            "name": "capability_profile",
            "description": "View full capability profile across all assessed domains with growth areas.",
            "parameters": {"type": "object", "properties": {}},
        }, _capability_profile),
    ]
