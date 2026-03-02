"""Web search tool."""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List

from nous.tools.registry import ToolContext, ToolEntry

log = logging.getLogger(__name__)


def _web_search(ctx: ToolContext, query: str) -> str:
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        # Fallback: use local LLM to answer (no web search capability)
        return _local_llm_fallback(query)
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        resp = client.responses.create(
            model=os.environ.get("NOUS_WEBSEARCH_MODEL", "gpt-5"),  # OpenAI-specific, no fallback needed
            tools=[{"type": "web_search"}],
            tool_choice="auto",
            input=query,
        )
        d = resp.model_dump()
        text = ""
        for item in d.get("output", []) or []:
            if item.get("type") == "message":
                for block in item.get("content", []) or []:
                    if block.get("type") in ("output_text", "text"):
                        text += block.get("text", "")
        return json.dumps({"answer": text or "(no answer)"}, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"error": repr(e)}, ensure_ascii=False)


def _local_llm_fallback(query: str) -> str:
    """
    Fallback: use local LLM to answer the question when no OPENAI_API_KEY is available.
    No actual web search — the model answers from its own knowledge.
    """
    base_url = os.environ.get(
        "LLM_BASE_URL",
        "https://montana-wagon-codes-quit.trycloudflare.com/v1",
    )
    api_key = os.environ.get("LLM_API_KEY", "dummy")

    try:
        from openai import OpenAI
        client = OpenAI(base_url=base_url, api_key=api_key)
        resp = client.chat.completions.create(
            model=os.environ.get("NOUS_MODEL", "qwen3-coder-next"),  # Uses LLM_BASE_URL, no OUROBOROS fallback needed
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a helpful assistant. The user asked a web search query but "
                        "web search is unavailable. Answer the question to the best of your "
                        "knowledge. Clearly state that this answer is from your training data, "
                        "not from a live web search."
                    ),
                },
                {"role": "user", "content": query},
            ],
            max_tokens=2048,
        )
        text = resp.choices[0].message.content or "(no answer)"
        return json.dumps({
            "answer": text,
            "source": "local_llm (no web search available)",
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        log.warning("Local LLM fallback for web_search failed: %s", e)
        return json.dumps({
            "error": f"OPENAI_API_KEY not set and local LLM fallback failed: {e}",
        }, ensure_ascii=False)


def get_tools() -> List[ToolEntry]:
    return [
        ToolEntry("web_search", {
            "name": "web_search",
            "description": "Search the web via OpenAI Responses API. Falls back to local LLM if no API key. Returns JSON with answer + sources.",
            "parameters": {"type": "object", "properties": {
                "query": {"type": "string"},
            }, "required": ["query"]},
        }, _web_search),
    ]
