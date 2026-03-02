"""
Nous — Runtime environment detection.

Detects whether running on Google Colab or local machine,
and builds appropriate configuration.
"""

from __future__ import annotations

import logging
import os
from nous.utils import get_env
import pathlib
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class RuntimeConfig:
    """Immutable runtime configuration snapshot."""
    environment: str          # "colab" | "local"
    drive_root: pathlib.Path
    repo_dir: pathlib.Path
    use_drive_mount: bool


def detect_environment() -> str:
    """Detect runtime environment.

    Returns "colab" if google.colab is importable, otherwise "local".
    """
    try:
        import google.colab  # noqa: F401
        return "colab"
    except ImportError:
        return "local"


def build_runtime_config() -> RuntimeConfig:
    """Build runtime configuration based on environment and env vars.

    Env vars:
        NOUS_DRIVE_ROOT: Override drive root (local default: ~/.nous/)
        NOUS_REPO_DIR: Override repo directory (local default: cwd)
    """
    env = detect_environment()

    if env == "colab":
        drive_root = pathlib.Path(
            get_env("NOUS_DRIVE_ROOT", "/content/drive/MyDrive/Nous")
        )
        repo_dir = pathlib.Path(
            get_env("NOUS_REPO_DIR", "/content/nous_repo")
        )
        use_drive = True
    else:
        home_nous = pathlib.Path.home() / ".nous"
        drive_root = pathlib.Path(
            get_env("NOUS_DRIVE_ROOT", str(home_nous))
        )
        repo_dir = pathlib.Path(
            get_env("NOUS_REPO_DIR", str(pathlib.Path.cwd()))
        )
        use_drive = False

    drive_root.mkdir(parents=True, exist_ok=True)

    config = RuntimeConfig(
        environment=env,
        drive_root=drive_root,
        repo_dir=repo_dir,
        use_drive_mount=use_drive,
    )
    log.info("Runtime: env=%s drive=%s repo=%s", env, drive_root, repo_dir)
    return config


# Singleton — built once on first import
_config: RuntimeConfig | None = None


def get_runtime_config() -> RuntimeConfig:
    """Get or create the singleton runtime config."""
    global _config
    if _config is None:
        _config = build_runtime_config()
    return _config
