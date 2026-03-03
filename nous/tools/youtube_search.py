"""YouTube and Google Search tools.

YouTube uses the YouTube Data API v3 (via Colab auth or API key).
Google Search uses Custom Search JSON API or fallback to web scraping.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List

from nous.tools.registry import ToolContext, ToolEntry

log = logging.getLogger(__name__)

# Cached YouTube service — built once, reused across all tool calls.
_cached_youtube = None


# ── YouTube Tools ────────────────────────────────────────────

def _get_youtube_service():
    """Build YouTube API service (cached after first successful build)."""
    global _cached_youtube
    if _cached_youtube is not None:
        return _cached_youtube

    # Try API key first (faster, no OAuth needed)
    api_key = os.environ.get("YOUTUBE_API_KEY") or os.environ.get("GOOGLE_API_KEY", "")
    if api_key:
        try:
            from googleapiclient.discovery import build
            _cached_youtube = build("youtube", "v3", developerKey=api_key)
            return _cached_youtube
        except Exception as e:
            log.debug("YouTube API key auth failed: %s", e)

    # Fall back to Colab OAuth (pre-authenticated at startup)
    try:
        from google.colab import auth  # type: ignore
        auth.authenticate_user()
        from googleapiclient.discovery import build
        from google.auth import default
        creds, _ = default(scopes=["https://www.googleapis.com/auth/youtube.readonly"])
        _cached_youtube = build("youtube", "v3", credentials=creds)
        return _cached_youtube
    except ImportError:
        return None
    except Exception as e:
        log.warning("YouTube auth failed: %s", e)
        return None


def _youtube_search(ctx: ToolContext, query: str, max_results: int = 10) -> str:
    """Search YouTube for videos."""
    service = _get_youtube_service()
    if not service:
        # Fallback: use web search tool
        return _youtube_search_fallback(query, max_results)

    try:
        results = service.search().list(
            q=query,
            part="snippet",
            type="video",
            maxResults=min(max_results, 25),
            order="relevance",
        ).execute()

        videos = []
        for item in results.get("items", []):
            snippet = item.get("snippet", {})
            video_id = item.get("id", {}).get("videoId", "")
            videos.append({
                "title": snippet.get("title", ""),
                "channel": snippet.get("channelTitle", ""),
                "description": (snippet.get("description", "") or "")[:200],
                "published": snippet.get("publishedAt", ""),
                "video_id": video_id,
                "url": f"https://www.youtube.com/watch?v={video_id}",
                "thumbnail": snippet.get("thumbnails", {}).get("default", {}).get("url", ""),
            })

        return json.dumps({"videos": videos, "count": len(videos), "query": query}, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"error": f"YouTube search failed: {e}"})


def _youtube_search_fallback(query: str, max_results: int) -> str:
    """Fallback YouTube search using web scraping when API is unavailable."""
    try:
        import urllib.request
        import urllib.parse
        import re

        search_url = f"https://www.youtube.com/results?search_query={urllib.parse.quote(query)}"
        req = urllib.request.Request(search_url, headers={"User-Agent": "Mozilla/5.0"})
        resp = urllib.request.urlopen(req, timeout=15)
        html = resp.read().decode("utf-8", errors="replace")

        # Extract video IDs from the page
        video_ids = re.findall(r'"videoId":"([a-zA-Z0-9_-]{11})"', html)
        seen = []
        for vid in video_ids:
            if vid not in seen:
                seen.append(vid)
            if len(seen) >= max_results:
                break

        videos = [{"video_id": vid, "url": f"https://www.youtube.com/watch?v={vid}"} for vid in seen]
        return json.dumps({
            "videos": videos,
            "count": len(videos),
            "query": query,
            "source": "web_scrape (API unavailable)",
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"error": f"YouTube fallback search failed: {e}"})


def _youtube_video_info(ctx: ToolContext, video_id: str) -> str:
    """Get detailed info about a YouTube video by ID."""
    service = _get_youtube_service()
    if not service:
        return json.dumps({"video_id": video_id, "url": f"https://www.youtube.com/watch?v={video_id}",
                           "note": "YouTube API unavailable — only URL returned"})

    try:
        results = service.videos().list(
            id=video_id,
            part="snippet,statistics,contentDetails",
        ).execute()

        items = results.get("items", [])
        if not items:
            return json.dumps({"error": f"Video {video_id} not found"})

        item = items[0]
        snippet = item.get("snippet", {})
        stats = item.get("statistics", {})
        details = item.get("contentDetails", {})

        return json.dumps({
            "video_id": video_id,
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "title": snippet.get("title", ""),
            "channel": snippet.get("channelTitle", ""),
            "description": (snippet.get("description", "") or "")[:1000],
            "published": snippet.get("publishedAt", ""),
            "duration": details.get("duration", ""),
            "views": stats.get("viewCount", ""),
            "likes": stats.get("likeCount", ""),
            "comments": stats.get("commentCount", ""),
            "tags": (snippet.get("tags", []) or [])[:10],
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"error": f"YouTube video info failed: {e}"})


# ── Google Search Tool ───────────────────────────────────────

def _google_search(ctx: ToolContext, query: str, max_results: int = 10) -> str:
    """Search Google. Uses Custom Search API if configured, otherwise web scrape fallback."""
    api_key = os.environ.get("GOOGLE_API_KEY", "")
    cx = os.environ.get("GOOGLE_SEARCH_CX", "")

    if api_key and cx:
        return _google_search_api(query, api_key, cx, max_results)
    return _google_search_fallback(query, max_results)


def _google_search_api(query: str, api_key: str, cx: str, max_results: int) -> str:
    """Google Custom Search JSON API."""
    try:
        from googleapiclient.discovery import build
        service = build("customsearch", "v1", developerKey=api_key)
        results = service.cse().list(q=query, cx=cx, num=min(max_results, 10)).execute()

        items = []
        for item in results.get("items", []):
            items.append({
                "title": item.get("title", ""),
                "link": item.get("link", ""),
                "snippet": item.get("snippet", ""),
            })

        return json.dumps({"results": items, "count": len(items), "query": query}, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"error": f"Google Search API failed: {e}"})


def _google_search_fallback(query: str, max_results: int) -> str:
    """Fallback Google search via web scraping."""
    try:
        import urllib.request
        import urllib.parse
        import re

        search_url = f"https://www.google.com/search?q={urllib.parse.quote(query)}&num={max_results}"
        req = urllib.request.Request(search_url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        })
        resp = urllib.request.urlopen(req, timeout=15)
        html = resp.read().decode("utf-8", errors="replace")

        # Extract search result links and titles
        results = []
        # Match patterns like <a href="/url?q=https://example.com/...
        links = re.findall(r'<a href="/url\?q=([^&"]+)&', html)
        titles = re.findall(r'<h3[^>]*>(.*?)</h3>', html, re.DOTALL)

        for i, link in enumerate(links[:max_results]):
            link = urllib.parse.unquote(link)
            if link.startswith("http"):
                title = ""
                if i < len(titles):
                    title = re.sub(r'<[^>]+>', '', titles[i]).strip()
                results.append({"title": title, "link": link})

        return json.dumps({
            "results": results,
            "count": len(results),
            "query": query,
            "source": "web_scrape (API key not configured)",
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"error": f"Google search fallback failed: {e}"})


# ── Tool Registration ────────────────────────────────────────

def get_tools(ctx: ToolContext) -> List[ToolEntry]:
    return [
        ToolEntry("youtube_search", {
            "name": "youtube_search",
            "description": "Search YouTube for videos. Returns titles, channels, URLs, thumbnails.",
            "parameters": {"type": "object", "properties": {
                "query": {"type": "string"},
                "max_results": {"type": "integer", "default": 10},
            }, "required": ["query"]},
        }, _youtube_search),
        ToolEntry("youtube_video_info", {
            "name": "youtube_video_info",
            "description": "Get detailed info about a YouTube video: title, description, views, likes, duration.",
            "parameters": {"type": "object", "properties": {
                "video_id": {"type": "string"},
            }, "required": ["video_id"]},
        }, _youtube_video_info),
        ToolEntry("google_search", {
            "name": "google_search",
            "description": "Search Google. Returns titles, links, and snippets. Works with or without API key.",
            "parameters": {"type": "object", "properties": {
                "query": {"type": "string"},
                "max_results": {"type": "integer", "default": 10},
            }, "required": ["query"]},
        }, _google_search),
    ]
