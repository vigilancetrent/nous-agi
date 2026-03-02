"""Test runtime environment detection."""

import os
import pathlib
import pytest


def test_detect_local_environment():
    """Should detect local environment when google.colab not available."""
    from nous.runtime import detect_environment
    # In test environment, google.colab should not be available
    assert detect_environment() == "local"


def test_build_runtime_config_local():
    """RuntimeConfig should have correct local defaults."""
    from nous.runtime import build_runtime_config
    old_root = os.environ.get("NOUS_DRIVE_ROOT")
    old_repo = os.environ.get("NOUS_REPO_DIR")
    try:
        os.environ.pop("NOUS_DRIVE_ROOT", None)
        os.environ.pop("NOUS_REPO_DIR", None)
        config = build_runtime_config()
        assert config.environment == "local"
        assert config.use_drive_mount is False
        assert config.drive_root == pathlib.Path.home() / ".nous"
    finally:
        if old_root:
            os.environ["NOUS_DRIVE_ROOT"] = old_root
        if old_repo:
            os.environ["NOUS_REPO_DIR"] = old_repo


def test_runtime_config_env_override():
    """Env vars should override defaults."""
    from nous.runtime import build_runtime_config
    import nous.runtime
    nous.runtime._config = None  # Reset singleton

    old_root = os.environ.get("NOUS_DRIVE_ROOT")
    old_repo = os.environ.get("NOUS_REPO_DIR")
    try:
        os.environ["NOUS_DRIVE_ROOT"] = "/tmp/test_nous"
        os.environ["NOUS_REPO_DIR"] = "/tmp/test_repo"
        config = build_runtime_config()
        assert config.drive_root == pathlib.Path("/tmp/test_nous")
        assert config.repo_dir == pathlib.Path("/tmp/test_repo")
    finally:
        nous.runtime._config = None
        if old_root:
            os.environ["NOUS_DRIVE_ROOT"] = old_root
        else:
            os.environ.pop("NOUS_DRIVE_ROOT", None)
        if old_repo:
            os.environ["NOUS_REPO_DIR"] = old_repo
        else:
            os.environ.pop("NOUS_REPO_DIR", None)
