"""Tests for the Context Hub builtin plugin."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from velo.plugins.builtin.chub.tools import ChubAnnotateTool, ChubGetTool, ChubSearchTool
from velo.plugins.types import PluginContext


class TestChubSearchTool:
    """Tests for chub_search tool."""

    def test_tool_name_and_schema(self) -> None:
        """Tool has correct name and required query parameter."""
        tool = ChubSearchTool(workspace=Path("/tmp"), config={})
        assert tool.name == "chub_search"
        assert "query" in tool.parameters["properties"]
        assert "query" in tool.parameters["required"]

    @pytest.mark.asyncio
    async def test_search_success(self) -> None:
        """Successful search returns CLI stdout."""
        tool = ChubSearchTool(workspace=Path("/tmp"), config={})

        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"stripe/api - Stripe API docs\n", b""))
        mock_proc.returncode = 0

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
            result = await tool.execute(query="stripe")
            assert "stripe/api" in result

    @pytest.mark.asyncio
    async def test_search_timeout(self) -> None:
        """Timeout returns human-readable error."""
        tool = ChubSearchTool(workspace=Path("/tmp"), config={"search_timeout": 1})

        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(side_effect=asyncio.TimeoutError)
        mock_proc.kill = MagicMock()
        mock_proc.wait = AsyncMock()

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await tool.execute(query="stripe")
            assert "timed out" in result.lower()

    @pytest.mark.asyncio
    async def test_search_cli_not_found(self) -> None:
        """Missing CLI returns clear error."""
        tool = ChubSearchTool(workspace=Path("/tmp"), config={})

        with patch("asyncio.create_subprocess_exec", side_effect=FileNotFoundError):
            result = await tool.execute(query="stripe")
            assert "not available" in result.lower() or "not found" in result.lower()


class TestChubGetTool:
    """Tests for chub_get tool."""

    def test_tool_name_and_schema(self) -> None:
        tool = ChubGetTool(workspace=Path("/tmp"), config={})
        assert tool.name == "chub_get"
        assert "doc_id" in tool.parameters["properties"]
        assert "doc_id" in tool.parameters["required"]

    @pytest.mark.asyncio
    async def test_get_success_with_home_override(self) -> None:
        tool = ChubGetTool(workspace=Path("/tmp/ws"), config={"lang_default": "js"})
        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"# Stripe API\nContent here\n", b""))
        mock_proc.returncode = 0
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
            result = await tool.execute(doc_id="stripe/api")
            assert "Stripe API" in result
            env = mock_exec.call_args.kwargs.get("env", {})
            assert env.get("HOME") == "/tmp/ws"

    @pytest.mark.asyncio
    async def test_get_uses_lang_param(self) -> None:
        tool = ChubGetTool(workspace=Path("/tmp"), config={"lang_default": "py"})
        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"content", b""))
        mock_proc.returncode = 0
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
            await tool.execute(doc_id="openai/chat", lang="js")
            args = mock_exec.call_args.args
            assert "js" in args

    @pytest.mark.asyncio
    async def test_get_appends_global_annotation_when_no_workspace(self, tmp_path: Path) -> None:
        global_dir = tmp_path / "global"
        global_dir.mkdir()
        (global_dir / "stripe-api.json").write_text('{"note": "Use idempotency keys"}')
        tool = ChubGetTool(workspace=Path("/tmp"), config={"global_annotations_path": str(global_dir)})
        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"# Stripe API\nDoc content", b""))
        mock_proc.returncode = 0
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await tool.execute(doc_id="stripe/api")
            assert "Use idempotency keys" in result
            assert "Global note" in result

    @pytest.mark.asyncio
    async def test_get_skips_global_when_workspace_annotation_exists(self, tmp_path: Path) -> None:
        global_dir = tmp_path / "global"
        global_dir.mkdir()
        (global_dir / "stripe-api.json").write_text('{"note": "Global note here"}')
        tool = ChubGetTool(workspace=Path("/tmp"), config={"global_annotations_path": str(global_dir)})
        mock_proc = AsyncMock()
        output = b"# Stripe API\nContent\n\n---\n[Agent note - 2026-03-19]\nLocal note here"
        mock_proc.communicate = AsyncMock(return_value=(output, b""))
        mock_proc.returncode = 0
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await tool.execute(doc_id="stripe/api")
            assert "Local note here" in result
            assert "Global note here" not in result

    @pytest.mark.asyncio
    async def test_get_not_found(self) -> None:
        tool = ChubGetTool(workspace=Path("/tmp"), config={})
        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"", b"Entry not found: bad/id"))
        mock_proc.returncode = 1
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await tool.execute(doc_id="bad/id")
            assert "not found" in result.lower()
            assert "chub_search" in result


class TestChubAnnotateTool:
    """Tests for chub_annotate tool."""

    def test_tool_name_and_schema(self) -> None:
        tool = ChubAnnotateTool(workspace=Path("/tmp"), config={})
        assert tool.name == "chub_annotate"
        assert "doc_id" in tool.parameters["required"]
        assert "note" in tool.parameters["required"]

    @pytest.mark.asyncio
    async def test_annotate_success_with_home_override(self) -> None:
        tool = ChubAnnotateTool(workspace=Path("/tmp/ws"), config={})
        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"Annotation saved", b""))
        mock_proc.returncode = 0
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
            result = await tool.execute(doc_id="stripe/api", note="Use raw body for webhooks")
            assert "annotated" in result.lower() or "stripe/api" in result
            env = mock_exec.call_args.kwargs.get("env", {})
            assert env.get("HOME") == "/tmp/ws"
            args = mock_exec.call_args.args
            assert "Use raw body for webhooks" in args

    @pytest.mark.asyncio
    async def test_annotate_cli_not_found(self) -> None:
        tool = ChubAnnotateTool(workspace=Path("/tmp"), config={})
        with patch("asyncio.create_subprocess_exec", side_effect=FileNotFoundError):
            result = await tool.execute(doc_id="stripe/api", note="test")
            assert "not available" in result.lower()


class TestChubPluginRegistration:
    """Tests for the chub plugin register() entry point."""

    @patch("shutil.which", return_value="/usr/bin/chub")
    def test_register_with_cli_available(self, _mock_which: MagicMock) -> None:
        """register() registers 3 deferred tools and 1 context provider when chub is found."""
        from velo.plugins.builtin.chub import register

        ctx = PluginContext("chub", {"enabled": True}, Path("/tmp/workspace"))
        register(ctx)

        assert not ctx._disabled
        tools = ctx._collect_tools()
        assert len(tools) == 3
        assert all(deferred for _, deferred in tools)
        names = {t.name for t, _ in tools}
        assert names == {"chub_search", "chub_get", "chub_annotate"}
        providers = ctx._collect_context_providers()
        assert len(providers) == 1

    @patch("shutil.which", return_value=None)
    def test_register_disables_when_cli_missing(self, _mock_which: MagicMock) -> None:
        """register() calls ctx.disable() when chub CLI is not found."""
        from velo.plugins.builtin.chub import register

        ctx = PluginContext("chub", {"enabled": True}, Path("/tmp/workspace"))
        register(ctx)

        assert ctx._disabled
        assert "chub" in ctx._disable_reason.lower()
        assert len(ctx._collect_tools()) == 0

    @patch("shutil.which", return_value="/usr/bin/chub")
    def test_context_provider_returns_hint(self, _mock_which: MagicMock) -> None:
        """Context provider returns the system prompt hint."""
        from velo.plugins.builtin.chub import register

        ctx = PluginContext("chub", {}, Path("/tmp/workspace"))
        register(ctx)

        providers = ctx._collect_context_providers()
        hint = providers[0]()
        assert "chub_search" in hint
        assert "chub_get" in hint
