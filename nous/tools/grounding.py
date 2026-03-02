"""
Nous — Grounding tools.

Persistent browser sessions and sandbox execution.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from nous.tools.registry import ToolContext, ToolEntry

_browser: Any = None
_sandbox: Any = None


def _get_browser(ctx: ToolContext):
    global _browser
    if _browser is None:
        from nous.grounding import PersistentBrowser
        _browser = PersistentBrowser(drive_root=ctx.drive_root)
    return _browser


def _get_sandbox():
    global _sandbox
    if _sandbox is None:
        from nous.grounding import SandboxEnvironment
        _sandbox = SandboxEnvironment()
    return _sandbox


async def _persistent_browse(args: Dict[str, Any], ctx: ToolContext) -> str:
    browser = _get_browser(ctx)
    action = args.get("action", "list")

    if action == "create":
        session = browser.get_or_create_session(args.get("session_name", "default"))
        return json.dumps({"status": "ready", "session": session}, default=str)
    elif action == "save":
        browser.save_session_state(
            args.get("session_name", ""),
            current_url=args.get("current_url", ""),
        )
        return json.dumps({"status": "saved"})
    elif action == "restore":
        state = browser.restore_session_state(args.get("session_name", ""))
        return json.dumps(state, default=str)
    elif action == "list":
        sessions = browser.list_sessions()
        return json.dumps({"sessions": sessions}, default=str)
    return json.dumps({"error": f"Unknown action: {action}"})


async def _sandbox_execute(args: Dict[str, Any], ctx: ToolContext) -> str:
    sandbox = _get_sandbox()
    action = args.get("action", "execute")

    if action == "create":
        image = args.get("image", "python:3.11-slim")
        sid = sandbox.create_sandbox(image)
        return json.dumps({"sandbox_id": sid, "status": "created"})
    elif action == "execute":
        return sandbox.execute_in_sandbox(
            args.get("sandbox_id", ""),
            args.get("command", "echo hello"),
            timeout=args.get("timeout", 60),
        )
    elif action == "destroy":
        return sandbox.destroy_sandbox(args.get("sandbox_id", ""))
    elif action == "list":
        return json.dumps({"sandboxes": sandbox.list_sandboxes()})
    return json.dumps({"error": f"Unknown action: {action}"})


def get_tools(ctx: ToolContext) -> List[ToolEntry]:
    return [
        ToolEntry("persistent_browse", {
            "name": "persistent_browse",
            "description": "Manage persistent browser sessions with cookie/state preservation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["create", "save", "restore", "list"]},
                    "session_name": {"type": "string", "description": "Name of browser session"},
                    "current_url": {"type": "string", "description": "Current URL to save"},
                },
                "required": ["action"],
            },
        }, _persistent_browse),
        ToolEntry("sandbox_execute", {
            "name": "sandbox_execute",
            "description": "Execute code in an isolated sandbox environment (Docker or fallback).",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["create", "execute", "destroy", "list"]},
                    "sandbox_id": {"type": "string", "description": "Sandbox ID for execute/destroy"},
                    "command": {"type": "string", "description": "Command to execute"},
                    "image": {"type": "string", "description": "Docker image for create (default: python:3.11-slim)"},
                    "timeout": {"type": "integer", "description": "Timeout in seconds (default 60)"},
                },
                "required": ["action"],
            },
        }, _sandbox_execute),
    ]
