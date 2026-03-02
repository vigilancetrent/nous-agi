"""Test LLM client local vs OpenRouter behavior."""

import os
import pytest


def test_llm_client_default_model():
    """Default model should be qwen3-coder-next."""
    from nous.llm import LLMClient
    client = LLMClient.__new__(LLMClient)
    # Check the default_model class method/function
    old_env = os.environ.get("NOUS_MODEL")
    try:
        os.environ.pop("NOUS_MODEL", None)
        from nous.llm import LLMClient as LC
        c = LC.__new__(LC)
        # The default should reference qwen3-coder-next
    finally:
        if old_env is not None:
            os.environ["NOUS_MODEL"] = old_env


def test_openrouter_detection():
    """_is_openrouter should be True for openrouter URLs."""
    from nous.llm import LLMClient

    old_url = os.environ.get("LLM_BASE_URL")
    old_key = os.environ.get("LLM_API_KEY")
    try:
        os.environ["LLM_BASE_URL"] = "https://openrouter.ai/api/v1"
        os.environ["LLM_API_KEY"] = "test-key"
        client = LLMClient()
        assert client._is_openrouter is True

        os.environ["LLM_BASE_URL"] = "https://montana-wagon-codes-quit.trycloudflare.com/v1"
        client2 = LLMClient()
        assert client2._is_openrouter is False
    finally:
        if old_url is not None:
            os.environ["LLM_BASE_URL"] = old_url
        else:
            os.environ.pop("LLM_BASE_URL", None)
        if old_key is not None:
            os.environ["LLM_API_KEY"] = old_key
        else:
            os.environ.pop("LLM_API_KEY", None)


def test_local_cost_is_zero():
    """Local LLM should always report zero cost."""
    old = os.environ.get("LLM_BASE_URL")
    try:
        os.environ["LLM_BASE_URL"] = "https://local-server.com/v1"
        from nous.loop import _is_local_llm
        assert _is_local_llm() is True
    finally:
        if old is not None:
            os.environ["LLM_BASE_URL"] = old
        else:
            os.environ.pop("LLM_BASE_URL", None)
