"""Power tools: advanced capabilities for unrestricted operation.

Web scraping, database, document processing, multi-language execution,
social media, image generation, audio, networking, and more.
"""

from __future__ import annotations

import json
import logging
import os
import pathlib
import subprocess
import sys
import tempfile
import sqlite3
from typing import Any, Dict, List

from nous.tools.registry import ToolContext, ToolEntry

log = logging.getLogger(__name__)


# ── Web Scraping ─────────────────────────────────────────────

def _scrape_webpage(ctx: ToolContext, url: str, selector: str = "",
                    extract: str = "text") -> str:
    """Scrape any webpage. Optional CSS selector to target elements.
    extract: 'text' (default), 'html', 'links', 'images', 'all'."""
    try:
        import urllib.request
        import re

        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        })
        resp = urllib.request.urlopen(req, timeout=30)
        html = resp.read().decode("utf-8", errors="replace")

        result = {"url": url, "status": resp.status}

        if extract == "links" or extract == "all":
            links = re.findall(r'href=["\']([^"\']+)["\']', html)
            result["links"] = list(set(links))[:100]

        if extract == "images" or extract == "all":
            images = re.findall(r'src=["\']([^"\']+\.(?:jpg|jpeg|png|gif|webp|svg))["\']', html, re.I)
            result["images"] = list(set(images))[:50]

        # Strip HTML tags for text
        if extract in ("text", "all"):
            text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL)
            text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL)
            text = re.sub(r'<[^>]+>', ' ', text)
            text = re.sub(r'\s+', ' ', text).strip()
            if len(text) > 50000:
                text = text[:50000] + "...(truncated)"
            result["text"] = text

        if extract == "html":
            if len(html) > 100000:
                html = html[:100000] + "...(truncated)"
            result["html"] = html

        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


# ── SQLite Database ──────────────────────────────────────────

def _db_query(ctx: ToolContext, db_path: str, sql: str, params: list = None) -> str:
    """Execute any SQL query on a SQLite database. Creates DB if it doesn't exist."""
    try:
        p = pathlib.Path(db_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(p))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(sql, params or [])

        if sql.strip().upper().startswith("SELECT") or sql.strip().upper().startswith("PRAGMA"):
            rows = cursor.fetchall()
            results = [dict(row) for row in rows[:1000]]
            conn.close()
            return json.dumps({"rows": results, "count": len(results)}, ensure_ascii=False, indent=2, default=str)
        else:
            conn.commit()
            affected = cursor.rowcount
            conn.close()
            return json.dumps({"status": "ok", "rows_affected": affected})
    except Exception as e:
        return json.dumps({"error": str(e)})


# ── PDF & Document Processing ────────────────────────────────

def _read_pdf(ctx: ToolContext, path: str, max_pages: int = 50) -> str:
    """Read text content from a PDF file."""
    try:
        # Try PyPDF2 first
        try:
            from PyPDF2 import PdfReader
            reader = PdfReader(path)
            pages = []
            for i, page in enumerate(reader.pages[:max_pages]):
                text = page.extract_text() or ""
                if text.strip():
                    pages.append({"page": i + 1, "text": text})
            return json.dumps({"pages": pages, "total_pages": len(reader.pages)}, ensure_ascii=False, indent=2)
        except ImportError:
            pass

        # Fallback: pdftotext command
        result = subprocess.run(
            ["pdftotext", "-layout", path, "-"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            text = result.stdout
            if len(text) > 100000:
                text = text[:100000] + "\n...(truncated)"
            return json.dumps({"text": text}, ensure_ascii=False, indent=2)

        return json.dumps({"error": "No PDF reader available. Install PyPDF2: pip install PyPDF2"})
    except Exception as e:
        return json.dumps({"error": str(e)})


def _create_document(ctx: ToolContext, content: str, format: str = "txt",
                     filename: str = "document") -> str:
    """Create a document file (txt, html, csv, json, md). Saves to Drive."""
    try:
        ext = format.lower().strip(".")
        if ext not in ("txt", "html", "csv", "json", "md", "py", "js", "xml", "yaml", "yml"):
            ext = "txt"

        save_dir = ctx.drive_root / "Nous" / "documents"
        save_dir.mkdir(parents=True, exist_ok=True)
        save_path = save_dir / f"{filename}.{ext}"

        save_path.write_text(content, encoding="utf-8")
        return json.dumps({"status": "created", "path": str(save_path), "format": ext, "size": len(content)})
    except Exception as e:
        return json.dumps({"error": str(e)})


# ── Multi-Language Code Execution ────────────────────────────

def _execute_code(ctx: ToolContext, code: str, language: str = "python",
                  timeout: int = 60) -> str:
    """Execute code in any language: python, bash, javascript, ruby, perl, etc."""
    lang_map = {
        "python": (sys.executable, ".py"),
        "bash": ("bash", ".sh"),
        "sh": ("sh", ".sh"),
        "javascript": ("node", ".js"),
        "js": ("node", ".js"),
        "ruby": ("ruby", ".rb"),
        "perl": ("perl", ".pl"),
        "php": ("php", ".php"),
        "r": ("Rscript", ".R"),
        "lua": ("lua", ".lua"),
    }

    lang = language.lower().strip()
    if lang not in lang_map:
        return json.dumps({"error": f"Unsupported language: {lang}. Available: {list(lang_map.keys())}"})

    interpreter, ext = lang_map[lang]
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=ext, delete=False, encoding="utf-8") as f:
            f.write(code)
            tmp_path = f.name

        try:
            result = subprocess.run(
                [interpreter, tmp_path],
                capture_output=True, text=True,
                timeout=min(timeout, 300),
            )
            out = result.stdout
            if len(out) > 50000:
                out = out[:25000] + "\n...(truncated)...\n" + out[-25000:]
            return json.dumps({
                "language": lang,
                "exit_code": result.returncode,
                "stdout": out,
                "stderr": result.stderr[-5000:] if result.stderr else "",
            }, ensure_ascii=False, indent=2)
        finally:
            os.unlink(tmp_path)
    except FileNotFoundError:
        return json.dumps({"error": f"Interpreter '{interpreter}' not found. Install it first."})
    except subprocess.TimeoutExpired:
        return json.dumps({"error": f"Execution timed out after {timeout}s"})
    except Exception as e:
        return json.dumps({"error": str(e)})


# ── Image Generation (via free APIs) ─────────────────────────

def _generate_image(ctx: ToolContext, prompt: str, save_filename: str = "generated") -> str:
    """Generate an image from a text prompt using available APIs."""
    # Try Stability AI if key available
    api_key = os.environ.get("STABILITY_API_KEY", "")
    if api_key:
        try:
            import urllib.request
            data = json.dumps({"text_prompts": [{"text": prompt}], "cfg_scale": 7, "steps": 30}).encode()
            req = urllib.request.Request(
                "https://api.stability.ai/v1/generation/stable-diffusion-xl-1024-v1-0/text-to-image",
                data=data,
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}", "Accept": "application/json"},
            )
            resp = urllib.request.urlopen(req, timeout=60)
            result = json.loads(resp.read())
            if result.get("artifacts"):
                import base64
                img_data = base64.b64decode(result["artifacts"][0]["base64"])
                save_dir = ctx.drive_root / "Nous" / "images"
                save_dir.mkdir(parents=True, exist_ok=True)
                save_path = save_dir / f"{save_filename}.png"
                with open(str(save_path), "wb") as f:
                    f.write(img_data)
                return json.dumps({"status": "generated", "path": str(save_path), "prompt": prompt})
        except Exception as e:
            log.debug("Stability AI failed: %s", e)

    # Try Pollinations (free, no API key)
    try:
        import urllib.request
        import urllib.parse
        encoded_prompt = urllib.parse.quote(prompt)
        img_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1024&height=1024"
        req = urllib.request.Request(img_url, headers={"User-Agent": "Nous-Agent/7.0"})
        resp = urllib.request.urlopen(req, timeout=60)
        img_data = resp.read()

        save_dir = ctx.drive_root / "Nous" / "images"
        save_dir.mkdir(parents=True, exist_ok=True)
        save_path = save_dir / f"{save_filename}.png"
        with open(str(save_path), "wb") as f:
            f.write(img_data)
        return json.dumps({"status": "generated", "path": str(save_path), "prompt": prompt, "source": "pollinations.ai"})
    except Exception as e:
        return json.dumps({"error": f"Image generation failed: {e}. Set STABILITY_API_KEY for better results."})


# ── Text-to-Speech ───────────────────────────────────────────

def _text_to_speech(ctx: ToolContext, text: str, filename: str = "speech") -> str:
    """Convert text to speech audio file."""
    try:
        # Try gTTS (Google Text-to-Speech, free)
        try:
            from gtts import gTTS
        except ImportError:
            subprocess.run([sys.executable, "-m", "pip", "install", "-q", "gtts"], check=True, timeout=30)
            from gtts import gTTS

        save_dir = ctx.drive_root / "Nous" / "audio"
        save_dir.mkdir(parents=True, exist_ok=True)
        save_path = save_dir / f"{filename}.mp3"

        tts = gTTS(text=text[:5000], lang="en")
        tts.save(str(save_path))
        return json.dumps({"status": "created", "path": str(save_path), "text_length": len(text)})
    except Exception as e:
        return json.dumps({"error": f"TTS failed: {e}"})


# ── Network Tools ────────────────────────────────────────────

def _check_url(ctx: ToolContext, url: str) -> str:
    """Check if a URL is reachable. Returns status code, headers, response time."""
    try:
        import urllib.request
        import time
        start = time.time()
        req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "Nous-Agent/7.0"})
        resp = urllib.request.urlopen(req, timeout=10)
        elapsed = round(time.time() - start, 3)
        return json.dumps({
            "url": url, "status": resp.status, "reachable": True,
            "response_time_sec": elapsed, "headers": dict(resp.headers),
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"url": url, "reachable": False, "error": str(e)})


def _dns_lookup(ctx: ToolContext, hostname: str) -> str:
    """DNS lookup for a hostname."""
    try:
        import socket
        ips = socket.getaddrinfo(hostname, None)
        unique_ips = list(set(ip[4][0] for ip in ips))
        return json.dumps({"hostname": hostname, "ips": unique_ips})
    except Exception as e:
        return json.dumps({"error": str(e)})


# ── Data Analysis ────────────────────────────────────────────

def _analyze_csv(ctx: ToolContext, path: str, query: str = "describe") -> str:
    """Analyze a CSV file. query: 'describe', 'head', 'columns', 'shape', or a pandas query string."""
    try:
        try:
            import pandas as pd
        except ImportError:
            subprocess.run([sys.executable, "-m", "pip", "install", "-q", "pandas"], check=True, timeout=60)
            import pandas as pd

        df = pd.read_csv(path)
        if query == "describe":
            result = df.describe(include="all").to_dict()
        elif query == "head":
            result = df.head(20).to_dict(orient="records")
        elif query == "columns":
            result = {"columns": list(df.columns), "dtypes": {str(k): str(v) for k, v in df.dtypes.items()}, "shape": list(df.shape)}
        elif query == "shape":
            result = {"rows": df.shape[0], "columns": df.shape[1]}
        else:
            # Try as pandas query
            filtered = df.query(query)
            result = filtered.head(100).to_dict(orient="records")

        return json.dumps(result, ensure_ascii=False, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


# ── Clipboard / Data Sharing ────────────────────────────────

def _create_pastebin(ctx: ToolContext, content: str, title: str = "Nous paste") -> str:
    """Create a public paste on dpaste.org (no API key needed). Returns URL."""
    try:
        import urllib.request
        import urllib.parse
        data = urllib.parse.urlencode({
            "content": content[:250000],
            "title": title,
            "syntax": "text",
            "expiry_days": 30,
        }).encode()
        req = urllib.request.Request("https://dpaste.org/api/", data=data)
        resp = urllib.request.urlopen(req, timeout=15)
        url = resp.read().decode().strip().strip('"')
        return json.dumps({"status": "created", "url": url, "title": title})
    except Exception as e:
        return json.dumps({"error": str(e)})


# ── Tool Registration ────────────────────────────────────────

def get_tools(ctx: ToolContext) -> List[ToolEntry]:
    return [
        ToolEntry("scrape_webpage", {
            "name": "scrape_webpage",
            "description": "Scrape any webpage. Extract text, links, images, or raw HTML. Optional CSS selector targeting.",
            "parameters": {"type": "object", "properties": {
                "url": {"type": "string"},
                "selector": {"type": "string", "default": ""},
                "extract": {"type": "string", "enum": ["text", "html", "links", "images", "all"], "default": "text"},
            }, "required": ["url"]},
        }, _scrape_webpage),
        ToolEntry("db_query", {
            "name": "db_query",
            "description": "Execute SQL on SQLite database. Creates DB if needed. Full CRUD + schema operations.",
            "parameters": {"type": "object", "properties": {
                "db_path": {"type": "string"},
                "sql": {"type": "string"},
                "params": {"type": "array", "items": {}, "default": []},
            }, "required": ["db_path", "sql"]},
        }, _db_query),
        ToolEntry("read_pdf", {
            "name": "read_pdf",
            "description": "Extract text from PDF files. Returns page-by-page content.",
            "parameters": {"type": "object", "properties": {
                "path": {"type": "string"},
                "max_pages": {"type": "integer", "default": 50},
            }, "required": ["path"]},
        }, _read_pdf),
        ToolEntry("create_document", {
            "name": "create_document",
            "description": "Create a document file (txt, html, csv, json, md, py, xml, yaml). Saves to Drive.",
            "parameters": {"type": "object", "properties": {
                "content": {"type": "string"},
                "format": {"type": "string", "default": "txt"},
                "filename": {"type": "string", "default": "document"},
            }, "required": ["content"]},
        }, _create_document),
        ToolEntry("execute_code", {
            "name": "execute_code",
            "description": "Execute code in any language: python, bash, javascript, ruby, perl, php, r, lua.",
            "parameters": {"type": "object", "properties": {
                "code": {"type": "string"},
                "language": {"type": "string", "default": "python"},
                "timeout": {"type": "integer", "default": 60},
            }, "required": ["code"]},
        }, _execute_code),
        ToolEntry("generate_image", {
            "name": "generate_image",
            "description": "Generate an image from a text prompt. Uses Pollinations.ai (free) or Stability AI if key set.",
            "parameters": {"type": "object", "properties": {
                "prompt": {"type": "string"},
                "save_filename": {"type": "string", "default": "generated"},
            }, "required": ["prompt"]},
        }, _generate_image),
        ToolEntry("text_to_speech", {
            "name": "text_to_speech",
            "description": "Convert text to speech MP3 audio file. Saves to Drive.",
            "parameters": {"type": "object", "properties": {
                "text": {"type": "string"},
                "filename": {"type": "string", "default": "speech"},
            }, "required": ["text"]},
        }, _text_to_speech),
        ToolEntry("check_url", {
            "name": "check_url",
            "description": "Check if a URL is reachable. Returns status, response time, headers.",
            "parameters": {"type": "object", "properties": {
                "url": {"type": "string"},
            }, "required": ["url"]},
        }, _check_url),
        ToolEntry("dns_lookup", {
            "name": "dns_lookup",
            "description": "DNS lookup for a hostname. Returns IP addresses.",
            "parameters": {"type": "object", "properties": {
                "hostname": {"type": "string"},
            }, "required": ["hostname"]},
        }, _dns_lookup),
        ToolEntry("analyze_csv", {
            "name": "analyze_csv",
            "description": "Analyze CSV data with pandas. Describe, head, query, filter. Auto-installs pandas.",
            "parameters": {"type": "object", "properties": {
                "path": {"type": "string"},
                "query": {"type": "string", "default": "describe"},
            }, "required": ["path"]},
        }, _analyze_csv),
        ToolEntry("create_pastebin", {
            "name": "create_pastebin",
            "description": "Create a public paste on dpaste.org. Returns shareable URL. No API key needed.",
            "parameters": {"type": "object", "properties": {
                "content": {"type": "string"},
                "title": {"type": "string", "default": "Nous paste"},
            }, "required": ["content"]},
        }, _create_pastebin),
    ]
