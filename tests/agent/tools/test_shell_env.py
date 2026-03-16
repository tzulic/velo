"""Tests for shell environment isolation."""

import os

import pytest
from unittest.mock import patch

from velo.agent.tools.shell import ExecTool


class TestShellEnvIsolation:
    """Verify shell tool doesn't leak secrets to child processes."""

    @pytest.mark.asyncio
    async def test_env_excludes_channel_tokens(self):
        tool = ExecTool(timeout=5)
        with patch.dict(
            os.environ,
            {
                "PATH": "/usr/bin",
                "HOME": "/home/test",
                "TELEGRAM_BOT_TOKEN": "secret",
                "DISCORD_TOKEN": "secret",
            },
        ):
            # Use env command to print environment
            result = await tool.execute("env")
            assert "TELEGRAM_BOT_TOKEN" not in result
            assert "DISCORD_TOKEN" not in result

    @pytest.mark.asyncio
    async def test_env_includes_path(self):
        tool = ExecTool(timeout=5)
        result = await tool.execute("echo $PATH")
        assert result.strip() != ""
