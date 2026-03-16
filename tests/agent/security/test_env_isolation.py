"""Tests for environment variable isolation."""

import os

import pytest
from unittest.mock import patch

from velo.agent.security.env_isolation import build_safe_env


class TestBuildSafeEnv:
    """Test safe environment builder."""

    def test_includes_safe_vars(self):
        with patch.dict(os.environ, {"PATH": "/usr/bin", "HOME": "/home/test", "USER": "test"}):
            env = build_safe_env()
            assert env["PATH"] == "/usr/bin"
            assert env["HOME"] == "/home/test"
            assert env["USER"] == "test"

    def test_excludes_secrets(self):
        with patch.dict(
            os.environ,
            {
                "PATH": "/usr/bin",
                "TELEGRAM_BOT_TOKEN": "secret123",
                "DISCORD_TOKEN": "secret456",
                "COMPOSIO_API_KEY": "secret789",
            },
        ):
            env = build_safe_env()
            assert "TELEGRAM_BOT_TOKEN" not in env
            assert "DISCORD_TOKEN" not in env
            assert "COMPOSIO_API_KEY" not in env

    def test_merges_explicit_overrides(self):
        with patch.dict(os.environ, {"PATH": "/usr/bin"}):
            env = build_safe_env(extra_env={"CUSTOM_VAR": "value"})
            assert env["CUSTOM_VAR"] == "value"
            assert env["PATH"] == "/usr/bin"

    def test_explicit_overrides_win(self):
        with patch.dict(os.environ, {"PATH": "/usr/bin"}):
            env = build_safe_env(extra_env={"PATH": "/custom/bin"})
            assert env["PATH"] == "/custom/bin"

    def test_passthrough_vars(self):
        with patch.dict(os.environ, {"PATH": "/usr/bin", "MY_CUSTOM": "allowed"}):
            env = build_safe_env(passthrough=["MY_CUSTOM"])
            assert env["MY_CUSTOM"] == "allowed"

    def test_empty_extra_env_gives_safe_baseline(self):
        """Empty extra_env should NOT be treated as None."""
        with patch.dict(os.environ, {"PATH": "/usr/bin", "SECRET": "x"}, clear=True):
            env = build_safe_env(extra_env={})
            assert "PATH" in env
            assert "SECRET" not in env

    def test_always_returns_dict_never_none(self):
        env = build_safe_env()
        assert isinstance(env, dict)
