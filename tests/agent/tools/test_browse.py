"""Tests for browse tool + BrowserSession."""

import json
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

from velo.agent.tools.browse import BrowserSession, WebBrowseTool, _html_to_markdown, _strip_tags


def _mock_patchright_module(mock_pw_cm: MagicMock):
    """Inject a mock patchright.async_api module into sys.modules.

    Reason: patchright may not be installed in the test runner's venv,
    so patch("patchright.async_api.async_playwright") would fail to
    resolve the module. Injecting directly into sys.modules bypasses this.

    Args:
        mock_pw_cm: Mock async_playwright context manager to inject.

    Returns:
        Tuple of (mock_module, cleanup_fn) to restore sys.modules after test.
    """
    mock_async_api = MagicMock()
    mock_async_api.async_playwright = MagicMock(return_value=mock_pw_cm)

    saved = {
        "patchright": sys.modules.get("patchright"),
        "patchright.async_api": sys.modules.get("patchright.async_api"),
    }
    sys.modules["patchright"] = MagicMock()
    sys.modules["patchright.async_api"] = mock_async_api

    def cleanup():
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v

    return mock_async_api, cleanup


# ---------------------------------------------------------------------------
# HTML helpers
# ---------------------------------------------------------------------------


class TestHtmlHelpers:
    """Tests for HTML helper functions."""

    def test_strip_tags_removes_html(self) -> None:
        """Basic HTML tags should be stripped."""
        assert _strip_tags("<b>bold</b>") == "bold"

    def test_strip_tags_removes_scripts(self) -> None:
        """Script tags and their content should be removed."""
        assert _strip_tags("<script>alert(1)</script>Hello") == "Hello"

    def test_html_to_markdown_converts_links(self) -> None:
        """Links should become markdown links."""
        result = _html_to_markdown('<a href="https://example.com">Click</a>')
        assert "[Click](https://example.com)" in result

    def test_html_to_markdown_converts_headings(self) -> None:
        """Headings should become markdown headings."""
        result = _html_to_markdown("<h2>Title</h2>")
        assert "## Title" in result


# ---------------------------------------------------------------------------
# BrowserSession
# ---------------------------------------------------------------------------


class TestBrowserSession:
    """Tests for BrowserSession lifecycle management."""

    @pytest.mark.asyncio
    async def test_ensure_page_launches_browser_on_first_call(self) -> None:
        """First call to ensure_page should launch browser."""
        mock_page = MagicMock()
        mock_page.is_closed.return_value = False

        mock_context = AsyncMock()
        mock_context.new_page = AsyncMock(return_value=mock_page)

        mock_browser = AsyncMock()
        mock_browser.new_context = AsyncMock(return_value=mock_context)

        mock_pw_instance = MagicMock()
        mock_pw_instance.chromium.launch = AsyncMock(return_value=mock_browser)

        mock_pw_cm = MagicMock()
        mock_pw_cm.start = AsyncMock(return_value=mock_pw_instance)

        _, cleanup = _mock_patchright_module(mock_pw_cm)
        try:
            session = BrowserSession()
            page = await session.ensure_page()
            assert page is mock_page
            mock_pw_instance.chromium.launch.assert_called_once()
        finally:
            cleanup()

    @pytest.mark.asyncio
    async def test_ensure_page_reuses_existing_page(self) -> None:
        """Subsequent calls should reuse the existing page."""
        session = BrowserSession()
        mock_page = MagicMock()
        mock_page.is_closed.return_value = False
        session._page = mock_page

        page = await session.ensure_page()
        assert page is mock_page

    @pytest.mark.asyncio
    async def test_ensure_page_relaunches_after_crash(self) -> None:
        """If page is closed, should relaunch browser."""
        session = BrowserSession()
        crashed_page = MagicMock()
        crashed_page.is_closed.return_value = True
        crashed_page.close = AsyncMock()
        session._page = crashed_page

        new_page = MagicMock()
        new_page.is_closed.return_value = False

        mock_context = AsyncMock()
        mock_context.new_page = AsyncMock(return_value=new_page)

        mock_browser = AsyncMock()
        mock_browser.new_context = AsyncMock(return_value=mock_context)

        mock_pw_instance = MagicMock()
        mock_pw_instance.chromium.launch = AsyncMock(return_value=mock_browser)

        mock_pw_cm = MagicMock()
        mock_pw_cm.start = AsyncMock(return_value=mock_pw_instance)

        _, cleanup = _mock_patchright_module(mock_pw_cm)
        try:
            page = await session.ensure_page()
            assert page is new_page
        finally:
            cleanup()

    @pytest.mark.asyncio
    async def test_close_cleans_up_all_handles(self) -> None:
        """close() should clean up page, context, browser, and playwright."""
        session = BrowserSession()
        session._page = AsyncMock()
        session._context = AsyncMock()
        session._browser = AsyncMock()
        session._playwright = AsyncMock()

        await session.close()

        assert session._page is None
        assert session._context is None
        assert session._browser is None
        assert session._playwright is None


# ---------------------------------------------------------------------------
# WebBrowseTool
# ---------------------------------------------------------------------------


def _make_mock_page() -> MagicMock:
    """Create a properly configured mock page for testing.

    Returns:
        MagicMock configured as a patchright Page with async methods.
    """
    mock_page = MagicMock()
    mock_page.url = "https://example.com"
    mock_page.is_closed.return_value = False
    mock_page.goto = AsyncMock()
    mock_page.title = AsyncMock(return_value="Example")
    mock_page.content = AsyncMock(return_value="<html><body><p>Hello world</p></body></html>")
    mock_page.click = AsyncMock()
    mock_page.fill = AsyncMock()
    mock_page.select_option = AsyncMock()
    mock_page.evaluate = AsyncMock(return_value=None)
    mock_page.screenshot = AsyncMock()
    mock_page.go_back = AsyncMock()
    mock_page.go_forward = AsyncMock()
    mock_page.reload = AsyncMock()
    mock_page.context = MagicMock()
    mock_page.context.cookies = AsyncMock(return_value=[])
    mock_page.context.add_cookies = AsyncMock()
    return mock_page


def _make_tool() -> tuple[WebBrowseTool, MagicMock]:
    """Create a WebBrowseTool with a mocked session and page."""
    session = BrowserSession()
    mock_page = _make_mock_page()
    session._page = mock_page
    tool = WebBrowseTool(session=session)
    return tool, mock_page


class TestWebBrowseTool:
    """Tests for WebBrowseTool."""

    @pytest.mark.asyncio
    async def test_goto_navigates_and_extracts(self) -> None:
        """goto action should navigate and return content."""
        tool, mock_page = _make_tool()

        result = await tool.execute(action="goto", url="https://example.com")
        data = json.loads(result)

        mock_page.goto.assert_called_once()
        assert data["url"] == "https://example.com"
        assert "content" in data

    @pytest.mark.asyncio
    async def test_goto_requires_url(self) -> None:
        """goto without url should return error."""
        tool, _ = _make_tool()

        result = await tool.execute(action="goto")
        data = json.loads(result)
        assert "error" in data

    @pytest.mark.asyncio
    async def test_click_action(self) -> None:
        """click action should click the selector."""
        tool, mock_page = _make_tool()

        result = await tool.execute(action="click", selector="#btn")
        data = json.loads(result)

        mock_page.click.assert_called_once_with("#btn", timeout=5000)
        assert data["action"] == "click"

    @pytest.mark.asyncio
    async def test_fill_action(self) -> None:
        """fill action should fill text into selector."""
        tool, mock_page = _make_tool()

        result = await tool.execute(action="fill", selector="#input", text="hello")
        data = json.loads(result)

        mock_page.fill.assert_called_once_with("#input", "hello")
        assert data["action"] == "fill"

    @pytest.mark.asyncio
    async def test_get_set_cookies(self) -> None:
        """get_cookies and set_cookies should interact with context."""
        tool, mock_page = _make_tool()
        mock_page.context.cookies = AsyncMock(return_value=[{"name": "session", "value": "abc"}])

        result = await tool.execute(action="get_cookies")
        data = json.loads(result)
        assert data["cookies"][0]["name"] == "session"

        cookies = [{"name": "token", "value": "xyz", "url": "https://example.com"}]
        result = await tool.execute(action="set_cookies", cookies=cookies)
        data = json.loads(result)
        assert data["status"] == "cookies_set"
        assert data["count"] == 1

    @pytest.mark.asyncio
    async def test_close_action(self) -> None:
        """close action should close the browser session."""
        tool, _ = _make_tool()

        result = await tool.execute(action="close")
        data = json.loads(result)
        assert data["status"] == "browser_closed"

    @pytest.mark.asyncio
    async def test_unknown_action_returns_error(self) -> None:
        """Unknown action should return an error."""
        tool, _ = _make_tool()

        result = await tool.execute(action="dance")
        data = json.loads(result)
        assert "error" in data
        assert "dance" in data["error"]

    @pytest.mark.asyncio
    async def test_exception_returns_error_json(self) -> None:
        """Exceptions during execution should return error JSON."""
        tool, mock_page = _make_tool()
        mock_page.goto.side_effect = TimeoutError("page load timed out")

        result = await tool.execute(action="goto", url="https://slow.example.com")
        data = json.loads(result)
        assert "error" in data
        assert "timed out" in data["error"]

    @pytest.mark.asyncio
    async def test_evaluate_action(self) -> None:
        """evaluate action should execute JavaScript."""
        tool, mock_page = _make_tool()
        mock_page.evaluate = AsyncMock(return_value=42)

        result = await tool.execute(action="evaluate", javascript="return 42")
        data = json.loads(result)
        assert data["result"] == 42

    @pytest.mark.asyncio
    async def test_navigation_actions(self) -> None:
        """back, forward, reload should call corresponding page methods."""
        tool, mock_page = _make_tool()

        for action in ("back", "forward", "reload"):
            result = await tool.execute(action=action)
            data = json.loads(result)
            assert data["action"] == action
