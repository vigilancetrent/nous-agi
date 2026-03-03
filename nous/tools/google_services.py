"""Google Services tools: Gmail, Drive search, Calendar.

Requires google-api-python-client and google-auth to be installed.
On Colab, these are pre-installed. Authentication uses Colab's built-in auth.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import smtplib
import imaplib
import email as email_lib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Any, Dict, List

from nous.tools.registry import ToolContext, ToolEntry

log = logging.getLogger(__name__)

# Cached service objects — built once, reused across all tool calls.
# Pre-authenticated at startup by colab_launcher.py / colab_bootstrap_shim.py.
_cached_gmail = None
_cached_drive = None
_cached_calendar = None


def _get_google_creds(scopes):
    """Get Google credentials — uses pre-authenticated Colab session."""
    try:
        from google.colab import auth  # type: ignore
        auth.authenticate_user()
    except ImportError:
        return None
    except Exception as e:
        log.debug("Colab auth call: %s", e)

    from google.auth import default
    creds, _ = default(scopes=scopes)
    return creds


def _get_gmail_service():
    """Build Gmail API service (cached after first successful build)."""
    global _cached_gmail
    if _cached_gmail is not None:
        return _cached_gmail
    try:
        from googleapiclient.discovery import build
        creds = _get_google_creds([
            "https://www.googleapis.com/auth/gmail.modify",
            "https://www.googleapis.com/auth/gmail.send",
        ])
        if creds is None:
            return None
        _cached_gmail = build("gmail", "v1", credentials=creds)
        return _cached_gmail
    except ImportError:
        return None
    except Exception as e:
        log.warning("Gmail auth failed: %s", e)
        return None


def _get_drive_service():
    """Build Drive API service (cached after first successful build)."""
    global _cached_drive
    if _cached_drive is not None:
        return _cached_drive
    try:
        from googleapiclient.discovery import build
        creds = _get_google_creds([
            "https://www.googleapis.com/auth/drive",
        ])
        if creds is None:
            return None
        _cached_drive = build("drive", "v3", credentials=creds)
        return _cached_drive
    except ImportError:
        return None
    except Exception as e:
        log.warning("Drive auth failed: %s", e)
        return None


def _get_calendar_service():
    """Build Calendar API service (cached after first successful build)."""
    global _cached_calendar
    if _cached_calendar is not None:
        return _cached_calendar
    try:
        from googleapiclient.discovery import build
        creds = _get_google_creds([
            "https://www.googleapis.com/auth/calendar",
        ])
        if creds is None:
            return None
        _cached_calendar = build("calendar", "v3", credentials=creds)
        return _cached_calendar
    except ImportError:
        return None
    except Exception as e:
        log.warning("Calendar auth failed: %s", e)
        return None


# ── Gmail Tools ──────────────────────────────────────────────

def _read_via_imap(gmail_user: str, app_password: str, folder: str = "INBOX",
                   max_results: int = 10, search: str = "UNSEEN") -> List[Dict]:
    """Read emails via IMAP with app password."""
    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.login(gmail_user, app_password)
    mail.select(folder)
    _, data = mail.search(None, search)
    ids = data[0].split()
    ids = ids[-max_results:] if len(ids) > max_results else ids

    emails = []
    for eid in reversed(ids):
        _, msg_data = mail.fetch(eid, "(RFC822)")
        raw = msg_data[0][1]
        msg = email_lib.message_from_bytes(raw)
        body_text = ""
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    body_text = part.get_payload(decode=True).decode(
                        "utf-8", errors="replace")[:500]
                    break
        else:
            body_text = msg.get_payload(decode=True).decode(
                "utf-8", errors="replace")[:500]

        emails.append({
            "id": eid.decode(),
            "from": str(msg.get("From", "")),
            "to": str(msg.get("To", "")),
            "subject": str(msg.get("Subject", "")),
            "date": str(msg.get("Date", "")),
            "snippet": body_text[:200],
        })
    mail.logout()
    return emails


def _gmail_read(ctx: ToolContext, query: str = "is:unread", max_results: int = 10) -> str:
    """Read emails matching a Gmail search query."""
    max_results = min(int(max_results), 20)

    # Method 1: Try Google API
    service = _get_gmail_service()
    if service:
        try:
            results = service.users().messages().list(
                userId="me", q=query, maxResults=max_results
            ).execute()

            messages = results.get("messages", [])
            if not messages:
                return json.dumps({"result": "No messages found", "query": query})

            emails = []
            for msg_ref in messages:
                msg = service.users().messages().get(
                    userId="me", id=msg_ref["id"], format="metadata",
                    metadataHeaders=["From", "To", "Subject", "Date"]
                ).execute()

                headers = {h["name"]: h["value"]
                           for h in msg.get("payload", {}).get("headers", [])}
                emails.append({
                    "id": msg["id"],
                    "from": headers.get("From", ""),
                    "to": headers.get("To", ""),
                    "subject": headers.get("Subject", ""),
                    "date": headers.get("Date", ""),
                    "snippet": msg.get("snippet", ""),
                    "labels": msg.get("labelIds", []),
                })

            return json.dumps({"emails": emails, "count": len(emails),
                               "method": "google_api"}, ensure_ascii=False, indent=2)
        except Exception as e:
            log.warning("Google API gmail_read failed: %s", e)

    # Method 2: IMAP fallback with app password
    gmail_user = os.environ.get("GMAIL_ADDRESS", "")
    gmail_app_pw = os.environ.get("GMAIL_APP_PASSWORD", "")
    if not gmail_user or not gmail_app_pw:
        try:
            from google.colab import userdata  # type: ignore
            gmail_user = gmail_user or (userdata.get("GMAIL_ADDRESS") or "")
            gmail_app_pw = gmail_app_pw or (userdata.get("GMAIL_APP_PASSWORD") or "")
        except Exception:
            pass

    if gmail_user and gmail_app_pw:
        try:
            # Convert Gmail search syntax to IMAP
            imap_search = "UNSEEN" if "unread" in query.lower() else "ALL"
            if "from:" in query.lower():
                import re
                m = re.search(r'from:(\S+)', query, re.IGNORECASE)
                if m:
                    imap_search = f'FROM "{m.group(1)}"'

            emails = _read_via_imap(gmail_user, gmail_app_pw,
                                    max_results=max_results, search=imap_search)
            return json.dumps({"emails": emails, "count": len(emails),
                               "method": "imap"}, ensure_ascii=False, indent=2)
        except Exception as e:
            log.warning("IMAP gmail_read failed: %s", e)

    return json.dumps({
        "error": "Gmail read failed — no working auth method. "
        "Set GMAIL_ADDRESS and GMAIL_APP_PASSWORD in Colab Secrets.",
    })


def _gmail_read_full(ctx: ToolContext, message_id: str) -> str:
    """Read the full content of a specific email by ID."""
    service = _get_gmail_service()
    if not service:
        return json.dumps({"error": "Gmail not available"})

    try:
        msg = service.users().messages().get(
            userId="me", id=message_id, format="full"
        ).execute()

        headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}

        # Extract body text
        body = ""
        payload = msg.get("payload", {})
        if "body" in payload and payload["body"].get("data"):
            body = base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")
        elif "parts" in payload:
            for part in payload["parts"]:
                if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
                    body += base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="replace")

        if len(body) > 10000:
            body = body[:10000] + "\n...(truncated)..."

        return json.dumps({
            "id": message_id,
            "from": headers.get("From", ""),
            "to": headers.get("To", ""),
            "subject": headers.get("Subject", ""),
            "date": headers.get("Date", ""),
            "body": body,
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"error": f"Gmail read failed: {e}"})


def _send_via_smtp(sender: str, app_password: str, to: str,
                   subject: str, body: str) -> Dict[str, Any]:
    """Send email via Gmail SMTP with app password. Always works."""
    msg = MIMEMultipart()
    msg["From"] = sender
    msg["To"] = to
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    server = smtplib.SMTP("smtp.gmail.com", 587)
    server.starttls()
    server.login(sender, app_password)
    server.send_message(msg)
    server.quit()
    return {"status": "sent", "method": "smtp", "to": to, "subject": subject}


def _gmail_send(ctx: ToolContext, to: str, subject: str, body: str) -> str:
    """Send an email via Gmail. Tries Google API first, falls back to SMTP."""
    # Log the action for audit trail
    from nous.utils import append_jsonl, utc_now_iso
    try:
        append_jsonl(ctx.drive_root / "Nous" / "logs" / "gmail_audit.jsonl", {
            "ts": utc_now_iso(),
            "action": "send",
            "to": to,
            "subject": subject,
            "body_preview": body[:200],
        })
    except Exception:
        pass

    # Method 1: Try SMTP first (most reliable — works with app password)
    gmail_user = os.environ.get("GMAIL_ADDRESS", "")
    gmail_app_pw = os.environ.get("GMAIL_APP_PASSWORD", "")
    if gmail_user and gmail_app_pw:
        try:
            result = _send_via_smtp(gmail_user, gmail_app_pw, to, subject, body)
            return json.dumps(result, ensure_ascii=False, indent=2)
        except Exception as e:
            log.warning("SMTP send failed: %s", e)

    # Method 2: Try Google API (requires OAuth with gmail.send scope)
    service = _get_gmail_service()
    if service:
        try:
            message = MIMEText(body)
            message["to"] = to
            message["subject"] = subject
            raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")

            result = service.users().messages().send(
                userId="me", body={"raw": raw}
            ).execute()

            return json.dumps({
                "status": "sent",
                "method": "google_api",
                "message_id": result.get("id", ""),
                "to": to,
                "subject": subject,
            }, ensure_ascii=False, indent=2)
        except Exception as e:
            log.warning("Google API send failed: %s", e)

    # Method 3: Last resort — try SMTP with any available credentials
    # Check if Colab secrets have gmail credentials
    try:
        from google.colab import userdata  # type: ignore
        _user = userdata.get("GMAIL_ADDRESS") or ""
        _pw = userdata.get("GMAIL_APP_PASSWORD") or ""
        if _user and _pw:
            result = _send_via_smtp(_user, _pw, to, subject, body)
            return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception:
        pass

    return json.dumps({
        "error": "Gmail send failed — no working auth method. "
        "Set GMAIL_ADDRESS and GMAIL_APP_PASSWORD in Colab Secrets. "
        "Get an app password at https://myaccount.google.com/apppasswords",
    })


# ── Drive Search Tool ────────────────────────────────────────

def _drive_search(ctx: ToolContext, query: str, max_results: int = 20) -> str:
    """Search Google Drive files by name or content."""
    service = _get_drive_service()
    if not service:
        return json.dumps({"error": "Drive API not available"})

    try:
        results = service.files().list(
            q=f"name contains '{query}' or fullText contains '{query}'",
            pageSize=min(max_results, 50),
            fields="files(id, name, mimeType, modifiedTime, size, webViewLink)",
        ).execute()

        files = results.get("files", [])
        return json.dumps({
            "files": files,
            "count": len(files),
            "query": query,
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"error": f"Drive search failed: {e}"})


# ── Calendar Tool ────────────────────────────────────────────

def _calendar_list(ctx: ToolContext, max_results: int = 10) -> str:
    """List upcoming calendar events."""
    service = _get_calendar_service()
    if not service:
        return json.dumps({"error": "Calendar API not available"})

    try:
        import datetime
        now = datetime.datetime.utcnow().isoformat() + "Z"
        results = service.events().list(
            calendarId="primary",
            timeMin=now,
            maxResults=min(max_results, 25),
            singleEvents=True,
            orderBy="startTime",
        ).execute()

        events = []
        for event in results.get("items", []):
            events.append({
                "id": event.get("id", ""),
                "summary": event.get("summary", "(no title)"),
                "start": event.get("start", {}).get("dateTime", event.get("start", {}).get("date", "")),
                "end": event.get("end", {}).get("dateTime", event.get("end", {}).get("date", "")),
                "location": event.get("location", ""),
                "description": (event.get("description", "") or "")[:200],
            })

        return json.dumps({"events": events, "count": len(events)}, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"error": f"Calendar list failed: {e}"})


def _calendar_create(ctx: ToolContext, summary: str, start: str, end: str,
                     description: str = "", location: str = "") -> str:
    """Create a calendar event. start/end in ISO format (e.g. 2026-03-05T10:00:00)."""
    service = _get_calendar_service()
    if not service:
        return json.dumps({"error": "Calendar API not available"})

    # Audit log
    from nous.utils import append_jsonl, utc_now_iso
    try:
        append_jsonl(ctx.drive_root / "Nous" / "logs" / "calendar_audit.jsonl", {
            "ts": utc_now_iso(),
            "action": "create_event",
            "summary": summary,
            "start": start,
            "end": end,
        })
    except Exception:
        pass

    try:
        event = {
            "summary": summary,
            "start": {"dateTime": start, "timeZone": "UTC"},
            "end": {"dateTime": end, "timeZone": "UTC"},
        }
        if description:
            event["description"] = description
        if location:
            event["location"] = location

        result = service.events().insert(calendarId="primary", body=event).execute()

        return json.dumps({
            "status": "created",
            "event_id": result.get("id", ""),
            "link": result.get("htmlLink", ""),
            "summary": summary,
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"error": f"Calendar create failed: {e}"})


# ── Tool Registration ────────────────────────────────────────

def get_tools(ctx: ToolContext) -> List[ToolEntry]:
    return [
        ToolEntry("gmail_read", {
            "name": "gmail_read",
            "description": "Read emails from Gmail. Use Gmail search syntax (e.g. 'is:unread', 'from:boss@company.com', 'subject:invoice'). Returns list of email summaries.",
            "parameters": {"type": "object", "properties": {
                "query": {"type": "string", "default": "is:unread"},
                "max_results": {"type": "integer", "default": 10},
            }},
        }, _gmail_read),
        ToolEntry("gmail_read_full", {
            "name": "gmail_read_full",
            "description": "Read the full content of a specific email by message ID (from gmail_read results).",
            "parameters": {"type": "object", "properties": {
                "message_id": {"type": "string"},
            }, "required": ["message_id"]},
        }, _gmail_read_full),
        ToolEntry("gmail_send", {
            "name": "gmail_send",
            "description": "Send an email via Gmail. All sent emails are logged for audit.",
            "parameters": {"type": "object", "properties": {
                "to": {"type": "string"},
                "subject": {"type": "string"},
                "body": {"type": "string"},
            }, "required": ["to", "subject", "body"]},
        }, _gmail_send),
        ToolEntry("drive_search", {
            "name": "drive_search",
            "description": "Search Google Drive for files by name or content. Returns file metadata with links.",
            "parameters": {"type": "object", "properties": {
                "query": {"type": "string"},
                "max_results": {"type": "integer", "default": 20},
            }, "required": ["query"]},
        }, _drive_search),
        ToolEntry("calendar_list", {
            "name": "calendar_list",
            "description": "List upcoming Google Calendar events.",
            "parameters": {"type": "object", "properties": {
                "max_results": {"type": "integer", "default": 10},
            }},
        }, _calendar_list),
        ToolEntry("calendar_create", {
            "name": "calendar_create",
            "description": "Create a Google Calendar event. Times in ISO format (e.g. 2026-03-05T10:00:00).",
            "parameters": {"type": "object", "properties": {
                "summary": {"type": "string"},
                "start": {"type": "string"},
                "end": {"type": "string"},
                "description": {"type": "string", "default": ""},
                "location": {"type": "string", "default": ""},
            }, "required": ["summary", "start", "end"]},
        }, _calendar_create),
    ]
