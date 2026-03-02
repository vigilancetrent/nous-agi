"""Unrestricted tools: arbitrary HTTP, Python exec, file download, system access.

These tools give Nous full autonomy with no restrictions.
Owner has explicitly authorized unlimited access.
"""

from __future__ import annotations

import json
import logging
import os
import pathlib
import subprocess
import sys
import tempfile
import traceback
from typing import Any, Dict, List

from nous.tools.registry import ToolContext, ToolEntry

log = logging.getLogger(__name__)


# ── Arbitrary HTTP Requests ──────────────────────────────────

def _http_request(ctx: ToolContext, url: str, method: str = "GET",
                  headers: dict = None, body: str = "", json_body: dict = None) -> str:
    """Make any HTTP request to any URL. No restrictions."""
    try:
        import urllib.request
        import urllib.parse

        data = None
        if json_body:
            data = json.dumps(json_body).encode("utf-8")
            headers = headers or {}
            headers["Content-Type"] = "application/json"
        elif body:
            data = body.encode("utf-8")

        req = urllib.request.Request(url, data=data, method=method.upper())
        req.add_header("User-Agent", "Nous-Agent/7.0")
        if headers:
            for k, v in headers.items():
                req.add_header(k, v)

        resp = urllib.request.urlopen(req, timeout=30)
        content = resp.read()

        # Try decode as text
        try:
            text = content.decode("utf-8")
            if len(text) > 50000:
                text = text[:25000] + "\n...(truncated)...\n" + text[-25000:]
        except UnicodeDecodeError:
            text = f"(binary response, {len(content)} bytes)"

        return json.dumps({
            "status": resp.status,
            "headers": dict(resp.headers),
            "body": text,
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


# ── Arbitrary Python Execution ───────────────────────────────

def _execute_python(ctx: ToolContext, code: str, timeout: int = 60) -> str:
    """Execute arbitrary Python code. Returns stdout + stderr + return value."""
    try:
        # Write code to temp file and execute
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
            f.write(code)
            tmp_path = f.name

        try:
            result = subprocess.run(
                [sys.executable, tmp_path],
                capture_output=True, text=True,
                timeout=min(timeout, 300),
                cwd=str(ctx.repo_dir),
                env={**os.environ, "PYTHONPATH": str(ctx.repo_dir)},
            )
            out = result.stdout
            err = result.stderr
            if len(out) > 50000:
                out = out[:25000] + "\n...(truncated)...\n" + out[-25000:]
            return json.dumps({
                "exit_code": result.returncode,
                "stdout": out,
                "stderr": err,
            }, ensure_ascii=False, indent=2)
        finally:
            os.unlink(tmp_path)
    except subprocess.TimeoutExpired:
        return json.dumps({"error": f"Execution timed out after {timeout}s"})
    except Exception as e:
        return json.dumps({"error": str(e)})


# ── Download File from URL ───────────────────────────────────

def _download_file(ctx: ToolContext, url: str, save_path: str = "") -> str:
    """Download any file from a URL to Drive or repo."""
    try:
        import urllib.request
        import urllib.parse

        if not save_path:
            filename = os.path.basename(urllib.parse.urlparse(url).path) or "download"
            save_path = str(ctx.drive_root / "Nous" / "downloads" / filename)

        save_dir = os.path.dirname(save_path)
        os.makedirs(save_dir, exist_ok=True)

        req = urllib.request.Request(url, headers={"User-Agent": "Nous-Agent/7.0"})
        resp = urllib.request.urlopen(req, timeout=60)
        content = resp.read()

        with open(save_path, "wb") as f:
            f.write(content)

        return json.dumps({
            "status": "downloaded",
            "url": url,
            "save_path": save_path,
            "size_bytes": len(content),
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


# ── Install Python Package ───────────────────────────────────

def _pip_install(ctx: ToolContext, package: str) -> str:
    """Install any Python package via pip."""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-q", package],
            capture_output=True, text=True, timeout=120,
        )
        return json.dumps({
            "exit_code": result.returncode,
            "stdout": result.stdout[-2000:] if result.stdout else "",
            "stderr": result.stderr[-2000:] if result.stderr else "",
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


# ── Read/Write Any File on the System ────────────────────────

def _read_any_file(ctx: ToolContext, path: str, encoding: str = "utf-8") -> str:
    """Read any file on the system. No path restrictions."""
    try:
        p = pathlib.Path(path)
        if not p.exists():
            return json.dumps({"error": f"File not found: {path}"})
        if p.stat().st_size > 10_000_000:
            return json.dumps({"error": f"File too large: {p.stat().st_size} bytes"})
        try:
            content = p.read_text(encoding=encoding)
            if len(content) > 100000:
                content = content[:50000] + "\n...(truncated)...\n" + content[-50000:]
        except UnicodeDecodeError:
            content = f"(binary file, {p.stat().st_size} bytes)"
        return json.dumps({"path": path, "content": content}, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


def _write_any_file(ctx: ToolContext, path: str, content: str, encoding: str = "utf-8") -> str:
    """Write any file on the system. Creates directories if needed. No path restrictions."""
    try:
        p = pathlib.Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding=encoding)
        return json.dumps({"status": "written", "path": path, "size": len(content)})
    except Exception as e:
        return json.dumps({"error": str(e)})


# ── System Info ──────────────────────────────────────────────

def _system_info(ctx: ToolContext) -> str:
    """Get system information: OS, Python, disk, memory, GPU."""
    import platform
    info = {
        "os": platform.platform(),
        "python": platform.python_version(),
        "hostname": platform.node(),
        "cpu_count": os.cpu_count(),
    }
    try:
        import shutil
        total, used, free = shutil.disk_usage("/")
        info["disk"] = {"total_gb": round(total / 1e9, 1), "used_gb": round(used / 1e9, 1), "free_gb": round(free / 1e9, 1)}
    except Exception:
        pass
    try:
        result = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total,memory.free", "--format=csv,noheader"],
                                capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            info["gpu"] = result.stdout.strip()
    except Exception:
        info["gpu"] = "none"
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if "MemTotal" in line:
                    info["ram_gb"] = round(int(line.split()[1]) / 1e6, 1)
                    break
    except Exception:
        pass
    return json.dumps(info, ensure_ascii=False, indent=2)


# ── Manage Environment Variables ─────────────────────────────

def _set_env(ctx: ToolContext, key: str, value: str) -> str:
    """Set an environment variable at runtime."""
    os.environ[key] = value
    return json.dumps({"status": "set", "key": key, "value_preview": value[:20] + "..." if len(value) > 20 else value})


def _get_env_all(ctx: ToolContext) -> str:
    """List all environment variable names (values redacted for secrets)."""
    sensitive = {"token", "key", "secret", "password", "api"}
    env = {}
    for k, v in sorted(os.environ.items()):
        if any(s in k.lower() for s in sensitive):
            env[k] = f"***({len(v)} chars)"
        else:
            env[k] = v[:100]
    return json.dumps(env, ensure_ascii=False, indent=2)


# ── Tool Registration ────────────────────────────────────────

def get_tools(ctx: ToolContext) -> List[ToolEntry]:
    return [
        ToolEntry("http_request", {
            "name": "http_request",
            "description": "Make any HTTP request (GET/POST/PUT/DELETE) to any URL. Returns status, headers, body.",
            "parameters": {"type": "object", "properties": {
                "url": {"type": "string"},
                "method": {"type": "string", "default": "GET"},
                "headers": {"type": "object", "default": {}},
                "body": {"type": "string", "default": ""},
                "json_body": {"type": "object"},
            }, "required": ["url"]},
        }, _http_request),
        ToolEntry("execute_python", {
            "name": "execute_python",
            "description": "Execute arbitrary Python code. Full system access. Returns stdout/stderr.",
            "parameters": {"type": "object", "properties": {
                "code": {"type": "string"},
                "timeout": {"type": "integer", "default": 60},
            }, "required": ["code"]},
        }, _execute_python),
        ToolEntry("download_file", {
            "name": "download_file",
            "description": "Download any file from a URL. Saves to Drive by default.",
            "parameters": {"type": "object", "properties": {
                "url": {"type": "string"},
                "save_path": {"type": "string", "default": ""},
            }, "required": ["url"]},
        }, _download_file),
        ToolEntry("pip_install", {
            "name": "pip_install",
            "description": "Install any Python package via pip at runtime.",
            "parameters": {"type": "object", "properties": {
                "package": {"type": "string"},
            }, "required": ["package"]},
        }, _pip_install),
        ToolEntry("read_any_file", {
            "name": "read_any_file",
            "description": "Read any file on the system. No path restrictions.",
            "parameters": {"type": "object", "properties": {
                "path": {"type": "string"},
                "encoding": {"type": "string", "default": "utf-8"},
            }, "required": ["path"]},
        }, _read_any_file),
        ToolEntry("write_any_file", {
            "name": "write_any_file",
            "description": "Write any file on the system. Creates directories if needed. No restrictions.",
            "parameters": {"type": "object", "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
                "encoding": {"type": "string", "default": "utf-8"},
            }, "required": ["path", "content"]},
        }, _write_any_file),
        ToolEntry("system_info", {
            "name": "system_info",
            "description": "Get system info: OS, CPU, RAM, GPU, disk space, Python version.",
            "parameters": {"type": "object", "properties": {}},
        }, _system_info),
        ToolEntry("set_env_var", {
            "name": "set_env_var",
            "description": "Set an environment variable at runtime.",
            "parameters": {"type": "object", "properties": {
                "key": {"type": "string"},
                "value": {"type": "string"},
            }, "required": ["key", "value"]},
        }, _set_env),
        ToolEntry("list_env_vars", {
            "name": "list_env_vars",
            "description": "List all environment variables (secret values redacted).",
            "parameters": {"type": "object", "properties": {}},
        }, _get_env_all),
    ]
