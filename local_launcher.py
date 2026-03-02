"""
Nous — Local launcher (no Colab dependencies).

Entry point for running Nous on a local machine.
Reads all configuration from environment variables.

Usage:
    export TELEGRAM_BOT_TOKEN=your_token
    export LLM_BASE_URL=https://montana-wagon-codes-quit.trycloudflare.com/v1
    python local_launcher.py
"""

from __future__ import annotations

import logging
import os
import sys
import pathlib

# Auto-load .env file if present (secrets stay out of source code)
_env_file = pathlib.Path(__file__).resolve().parent / ".env"
if _env_file.exists():
    for _line in _env_file.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _key, _, _val = _line.partition("=")
            os.environ.setdefault(_key.strip(), _val.strip())

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
)
log = logging.getLogger("nous.local")


def main() -> None:
    """Local entry point — no Colab, no Drive mount."""

    # Ensure nous package is importable
    repo_dir = pathlib.Path(__file__).resolve().parent
    if str(repo_dir) not in sys.path:
        sys.path.insert(0, str(repo_dir))

    # Set defaults for local mode
    os.environ.setdefault("LLM_BASE_URL", "https://montana-wagon-codes-quit.trycloudflare.com/v1")
    os.environ.setdefault("LLM_API_KEY", "dummy")
    os.environ.setdefault("NOUS_REPO_DIR", str(repo_dir))
    os.environ.setdefault("NOUS_DRIVE_ROOT", str(pathlib.Path.home() / ".nous"))

    # Validate required env vars
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not bot_token:
        log.error("TELEGRAM_BOT_TOKEN not set. Export it and retry.")
        sys.exit(1)

    # Import after path setup
    from nous.runtime import get_runtime_config
    config = get_runtime_config()
    log.info("Nous local launcher — env=%s, drive=%s", config.environment, config.drive_root)

    # Ensure local directories exist
    for subdir in ("logs", "state", "memory", "memory/knowledge"):
        (config.drive_root / subdir).mkdir(parents=True, exist_ok=True)

    # Import and start the agent in direct-chat mode
    from nous.agent import make_agent
    from nous.tools.registry import ToolContext

    ctx = ToolContext(
        repo_dir=config.repo_dir,
        drive_root=config.drive_root,
        branch_dev="nous",
        branch_stable="nous-stable",
    )

    agent = make_agent(ctx)

    # Start telegram polling loop
    from supervisor.telegram import TelegramClient
    tg = TelegramClient(bot_token)

    log.info("Nous is online. Send a message via Telegram.")

    import time
    offset = 0
    while True:
        try:
            updates = tg.get_updates(offset=offset, timeout=30)
            for upd in updates:
                offset = upd.get("update_id", 0) + 1
                msg = upd.get("message", {})
                text = msg.get("text", "").strip()
                chat_id = msg.get("chat", {}).get("id")
                if not text or not chat_id:
                    continue
                log.info("Message from %s: %s", chat_id, text[:80])
                reply = agent.handle_message(text, chat_id=chat_id)
                if reply:
                    tg.send_message(chat_id, reply)
        except KeyboardInterrupt:
            log.info("Shutting down.")
            break
        except Exception as e:
            log.error("Error in main loop: %s", e, exc_info=True)
            time.sleep(5)


if __name__ == "__main__":
    main()
