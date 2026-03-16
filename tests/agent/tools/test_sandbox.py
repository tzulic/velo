"""Tests for Docker sandbox execution."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from velo.agent.tools.sandbox import DockerSandbox
from velo.config.schema import ExecToolConfig


class TestDockerSandbox:
    def setup_method(self):
        """Reset cached Docker availability between tests."""
        import velo.agent.tools.sandbox as _mod

        _mod._docker_available = None

    @pytest.mark.asyncio
    async def test_docker_unavailable_raises(self, tmp_path: Path):
        config = ExecToolConfig(sandbox="docker")
        sandbox = DockerSandbox(config=config, workspace=tmp_path)
        with patch("velo.agent.tools.sandbox._check_docker", return_value=False):
            with pytest.raises(RuntimeError, match="Docker"):
                await sandbox.execute("echo hello")

    @pytest.mark.asyncio
    async def test_timeout_enforcement(self, tmp_path: Path):
        config = ExecToolConfig(sandbox="docker", docker_timeout=1)
        sandbox = DockerSandbox(config=config, workspace=tmp_path)
        with patch("velo.agent.tools.sandbox._check_docker", return_value=True):
            with patch("asyncio.create_subprocess_exec") as mock_proc:
                proc = AsyncMock()
                proc.communicate = AsyncMock(side_effect=asyncio.TimeoutError("timed out"))
                proc.kill = MagicMock()
                proc.returncode = -9
                mock_proc.return_value = proc
                output, code = await sandbox.execute("sleep 999", timeout=1)
                assert code != 0

    @pytest.mark.asyncio
    async def test_successful_execution(self, tmp_path: Path):
        config = ExecToolConfig(sandbox="docker")
        sandbox = DockerSandbox(config=config, workspace=tmp_path)
        with patch("velo.agent.tools.sandbox._check_docker", return_value=True):
            with patch("asyncio.create_subprocess_exec") as mock_proc:
                proc = AsyncMock()
                proc.communicate = AsyncMock(return_value=(b"hello\n", None))
                proc.returncode = 0
                mock_proc.return_value = proc
                output, code = await sandbox.execute("echo hello")
                assert code == 0
                assert "hello" in output

    @pytest.mark.asyncio
    async def test_cleanup_no_error(self, tmp_path: Path):
        config = ExecToolConfig(sandbox="docker")
        sandbox = DockerSandbox(config=config, workspace=tmp_path)
        await sandbox.cleanup()  # Should not raise
