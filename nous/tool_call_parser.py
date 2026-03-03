"""Parse raw tool call text from local LLMs into structured OpenAI format.

Many local models (Qwen, Llama, Mistral, etc.) output tool calls as raw text
tags instead of structured OpenAI-format tool_calls. This module handles:
  1. <tool_call>\n{"name": "fn", "arguments": {...}}\n</tool_call>
  2. <tool_call>\n<function=fn_name>\n{"arg": "val"}\n</function>\n</tool_call>
  3. ```tool_call\n{"name": "fn", "arguments": {...}}\n```
  4. <tool_call>\nfunction_name\n{json_args}\n</tool_call>
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any, Dict, List

_TOOL_CALL_TAG_RE = re.compile(
    r"<tool_call>\s*(.*?)\s*</tool_call>",
    re.DOTALL,
)
_FUNCTION_TAG_RE = re.compile(
    r"<function=(\w+)>\s*(.*?)\s*</function>",
    re.DOTALL,
)
_TOOL_CALL_FENCE_RE = re.compile(
    r"```tool_call\s*\n(.*?)\n\s*```",
    re.DOTALL,
)


def _make_tc(fn_name: str, args: Any) -> Dict[str, Any]:
    """Build an OpenAI-format tool_call dict."""
    if isinstance(args, dict):
        args_str = json.dumps(args)
    elif isinstance(args, str):
        try:
            json.loads(args)
            args_str = args
        except (json.JSONDecodeError, ValueError):
            args_str = json.dumps({"input": args})
    else:
        args_str = json.dumps(args)
    return {
        "id": f"call_{uuid.uuid4().hex[:24]}",
        "type": "function",
        "function": {"name": fn_name, "arguments": args_str},
    }


def parse_tool_calls_from_text(content: str) -> List[Dict[str, Any]]:
    """Extract structured tool calls from raw model text output.

    Returns list of OpenAI-format tool_call dicts, or empty list if none found.
    """
    if not content:
        return []

    parsed: List[Dict[str, Any]] = []

    # Pattern 1: <tool_call>...</tool_call> blocks
    for outer_match in _TOOL_CALL_TAG_RE.finditer(content):
        inner = outer_match.group(1).strip()

        # Sub-pattern A: <function=name>{...}</function>
        fn_match = _FUNCTION_TAG_RE.search(inner)
        if fn_match:
            fn_name = fn_match.group(1).strip()
            args_raw = fn_match.group(2).strip()
            try:
                args = json.loads(args_raw) if args_raw else {}
            except (json.JSONDecodeError, ValueError):
                args = {"input": args_raw}
            parsed.append(_make_tc(fn_name, args))
            continue

        # Sub-pattern B: raw JSON with "name" key
        try:
            obj = json.loads(inner)
            if isinstance(obj, dict) and "name" in obj:
                args = obj.get("arguments", obj.get("parameters", {}))
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except (json.JSONDecodeError, ValueError):
                        pass
                parsed.append(_make_tc(obj["name"], args))
                continue
        except (json.JSONDecodeError, ValueError):
            pass

        # Sub-pattern C: function_name\n{json_args} (two-line format)
        lines = inner.strip().split("\n", 1)
        if len(lines) == 2:
            fn_name = lines[0].strip().strip("()").strip()
            if fn_name and not fn_name.startswith("{"):
                try:
                    args = json.loads(lines[1].strip())
                    parsed.append(_make_tc(fn_name, args))
                    continue
                except (json.JSONDecodeError, ValueError):
                    pass

    if parsed:
        return parsed

    # Pattern 2: ```tool_call\n{json}\n```
    for fence_match in _TOOL_CALL_FENCE_RE.finditer(content):
        try:
            obj = json.loads(fence_match.group(1).strip())
            if isinstance(obj, dict) and "name" in obj:
                args = obj.get("arguments", obj.get("parameters", {}))
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except (json.JSONDecodeError, ValueError):
                        pass
                parsed.append(_make_tc(obj["name"], args))
        except (json.JSONDecodeError, ValueError):
            pass

    return parsed


def strip_tool_call_tags(content: str) -> str:
    """Remove parsed tool call markup from content, leaving surrounding text."""
    result = _TOOL_CALL_TAG_RE.sub("", content)
    result = _TOOL_CALL_FENCE_RE.sub("", result)
    return result.strip()
