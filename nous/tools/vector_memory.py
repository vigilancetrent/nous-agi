"""
Nous — Vector memory tools.

Semantic search across all memory sources.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from nous.tools.registry import ToolContext, ToolEntry


def _get_vmem(ctx: ToolContext):
    from nous.vector_memory import VectorMemory
    return VectorMemory(drive_root=ctx.drive_root)


async def _vector_search(args: Dict[str, Any], ctx: ToolContext) -> str:
    vmem = _get_vmem(ctx)
    query = args.get("query", "")
    sources = args.get("sources", None)
    top_k = args.get("top_k", 10)
    results = vmem.search(query, sources=sources, top_k=top_k)
    formatted = []
    for r in results:
        formatted.append({
            "source": r.get("source", ""),
            "text": r.get("text", "")[:300],
            "score": round(r.get("score", 0), 3),
            "metadata": {k: v for k, v in r.get("metadata", {}).items() if k != "embedding"},
        })
    return json.dumps({"results": formatted, "count": len(formatted)})


async def _vector_reindex(args: Dict[str, Any], ctx: ToolContext) -> str:
    vmem = _get_vmem(ctx)
    knowledge_dir = ctx.drive_root / "memory" / "knowledge" if ctx.drive_root else None
    counts = vmem.reindex_all(knowledge_dir=knowledge_dir)
    return json.dumps({"status": "reindexed", "counts": counts})


def get_tools(ctx: ToolContext) -> List[ToolEntry]:
    return [
        ToolEntry("vector_search", {
            "name": "vector_search",
            "description": "Semantic search across knowledge, chat history, and experiences.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "What to search for"},
                    "sources": {
                        "type": "array",
                        "items": {"type": "string", "enum": ["knowledge", "chat", "experience"]},
                        "description": "Sources to search (default: all)",
                    },
                    "top_k": {"type": "integer", "description": "Max results (default 10)"},
                },
                "required": ["query"],
            },
        }, _vector_search),
        ToolEntry("vector_reindex", {
            "name": "vector_reindex",
            "description": "Rebuild vector indices from knowledge files.",
            "parameters": {"type": "object", "properties": {}},
        }, _vector_reindex),
    ]
