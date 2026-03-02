"""
Nous — Grounding.

Persistent browser sessions and sandbox execution environments.
"""

from __future__ import annotations

import json
import logging
import os
from nous.utils import get_env
import pathlib
import subprocess
import time
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)


class PersistentBrowser:
    """Manage persistent browser sessions with state saving."""

    def __init__(self, drive_root: pathlib.Path | None = None):
        root = drive_root or pathlib.Path(get_env("NOUS_DRIVE_ROOT", str(pathlib.Path.home() / ".nous")))
        self._session_dir = root / "browser_sessions"
        self._session_dir.mkdir(parents=True, exist_ok=True)
        self._sessions: Dict[str, Dict[str, Any]] = {}
        self._load_sessions()

    def _load_sessions(self) -> None:
        index = self._session_dir / "sessions.json"
        if index.exists():
            try:
                self._sessions = json.loads(index.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                self._sessions = {}

    def _save_sessions(self) -> None:
        index = self._session_dir / "sessions.json"
        index.write_text(json.dumps(self._sessions, indent=2), encoding="utf-8")

    def get_or_create_session(self, name: str) -> Dict[str, Any]:
        """Get or create a named browser session."""
        if name in self._sessions:
            self._sessions[name]["last_accessed"] = time.time()
            self._save_sessions()
            return self._sessions[name]

        session = {
            "name": name,
            "created_at": time.time(),
            "last_accessed": time.time(),
            "cookies_file": str(self._session_dir / f"{name}_cookies.json"),
            "history": [],
            "status": "created",
        }
        self._sessions[name] = session
        self._save_sessions()
        return session

    def save_session_state(self, name: str, cookies: List[Dict] | None = None,
                            current_url: str = "") -> None:
        """Save browser session state."""
        if name not in self._sessions:
            return

        session = self._sessions[name]
        session["last_accessed"] = time.time()

        if cookies:
            cookies_path = pathlib.Path(session["cookies_file"])
            cookies_path.write_text(json.dumps(cookies, indent=2), encoding="utf-8")

        if current_url:
            session["current_url"] = current_url
            session.setdefault("history", []).append({
                "url": current_url, "timestamp": time.time()
            })

        self._save_sessions()

    def restore_session_state(self, name: str) -> Dict[str, Any]:
        """Restore a saved browser session."""
        if name not in self._sessions:
            return {"error": f"Session '{name}' not found"}

        session = self._sessions[name]
        cookies = []
        cookies_path = pathlib.Path(session.get("cookies_file", ""))
        if cookies_path.exists():
            try:
                cookies = json.loads(cookies_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                cookies = []

        return {
            "name": name,
            "cookies": cookies,
            "current_url": session.get("current_url", ""),
            "history_length": len(session.get("history", [])),
        }

    def list_sessions(self) -> List[Dict[str, Any]]:
        """List all browser sessions."""
        return [
            {"name": name, "created": s.get("created_at"), "last_used": s.get("last_accessed")}
            for name, s in self._sessions.items()
        ]


class SandboxEnvironment:
    """Execute code in isolated sandbox environments."""

    def __init__(self):
        self._sandboxes: Dict[str, Dict[str, Any]] = {}

    def create_sandbox(self, image: str = "python:3.11-slim") -> str:
        """Create a new sandbox environment. Returns sandbox ID."""
        import hashlib
        sandbox_id = hashlib.sha256(f"sandbox:{time.time()}".encode()).hexdigest()[:10]

        # Check if Docker is available
        try:
            subprocess.run(["docker", "version"], capture_output=True, check=True, timeout=5)
            has_docker = True
        except (subprocess.SubprocessError, FileNotFoundError):
            has_docker = False

        self._sandboxes[sandbox_id] = {
            "id": sandbox_id,
            "image": image,
            "created_at": time.time(),
            "has_docker": has_docker,
            "status": "created",
        }

        if has_docker:
            try:
                result = subprocess.run(
                    ["docker", "run", "-d", "--name", f"nous-sandbox-{sandbox_id}",
                     "--memory", "512m", "--cpus", "1", image, "sleep", "3600"],
                    capture_output=True, text=True, timeout=30,
                )
                if result.returncode == 0:
                    self._sandboxes[sandbox_id]["container_id"] = result.stdout.strip()
                    self._sandboxes[sandbox_id]["status"] = "running"
            except subprocess.SubprocessError as e:
                log.warning("Failed to create Docker sandbox: %s", e)
                self._sandboxes[sandbox_id]["status"] = "fallback"
        else:
            self._sandboxes[sandbox_id]["status"] = "fallback"

        return sandbox_id

    def execute_in_sandbox(self, sandbox_id: str, command: str, timeout: int = 60) -> str:
        """Execute a command in a sandbox."""
        sandbox = self._sandboxes.get(sandbox_id)
        if not sandbox:
            return f"Sandbox {sandbox_id} not found."

        if sandbox.get("status") == "running" and sandbox.get("container_id"):
            # Docker execution
            try:
                result = subprocess.run(
                    ["docker", "exec", sandbox["container_id"], "bash", "-c", command],
                    capture_output=True, text=True, timeout=timeout,
                )
                return json.dumps({
                    "stdout": result.stdout[-5000:],
                    "stderr": result.stderr[-2000:],
                    "returncode": result.returncode,
                })
            except subprocess.TimeoutExpired:
                return json.dumps({"error": "Command timed out", "timeout": timeout})
            except subprocess.SubprocessError as e:
                return json.dumps({"error": str(e)})
        else:
            # Fallback: subprocess with restrictions
            try:
                result = subprocess.run(
                    ["bash", "-c", command],
                    capture_output=True, text=True, timeout=timeout,
                    cwd="/tmp",
                )
                return json.dumps({
                    "stdout": result.stdout[-5000:],
                    "stderr": result.stderr[-2000:],
                    "returncode": result.returncode,
                    "note": "Executed in fallback mode (no Docker isolation)",
                })
            except subprocess.TimeoutExpired:
                return json.dumps({"error": "Command timed out"})
            except subprocess.SubprocessError as e:
                return json.dumps({"error": str(e)})

    def destroy_sandbox(self, sandbox_id: str) -> str:
        """Destroy a sandbox environment."""
        sandbox = self._sandboxes.pop(sandbox_id, None)
        if not sandbox:
            return f"Sandbox {sandbox_id} not found."

        if sandbox.get("container_id"):
            try:
                subprocess.run(
                    ["docker", "rm", "-f", sandbox["container_id"]],
                    capture_output=True, timeout=10,
                )
            except subprocess.SubprocessError:
                pass

        return f"Sandbox {sandbox_id} destroyed."

    def list_sandboxes(self) -> List[Dict[str, Any]]:
        """List all sandbox environments."""
        return [
            {"id": s["id"], "status": s["status"], "image": s.get("image", "")}
            for s in self._sandboxes.values()
        ]
