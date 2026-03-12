"""Browser tool: web_browse with persistent sessions using Patchright."""

import html
import json
import re
from typing import Any

from loguru import logger

from velo.agent.tools.base import Tool

# ---------------------------------------------------------------------------
# HTML helpers (ported from previous web.py for readability extraction)
# ---------------------------------------------------------------------------


def _strip_tags(text: str) -> str:
    """Remove HTML tags and decode entities.

    Args:
        text: Raw HTML string.

    Returns:
        Plain text with tags removed and entities decoded.
    """
    text = re.sub(r"<script[\s\S]*?</script>", "", text, flags=re.I)
    text = re.sub(r"<style[\s\S]*?</style>", "", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text).strip()


def _normalize(text: str) -> str:
    """Normalize whitespace in extracted text.

    Args:
        text: Text with irregular whitespace.

    Returns:
        Cleaned text with normalized spacing.
    """
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _html_to_markdown(raw_html: str) -> str:
    """Convert HTML to simple markdown.

    Args:
        raw_html: HTML content to convert.

    Returns:
        Markdown-formatted text.
    """
    text = re.sub(
        r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>([\s\S]*?)</a>',
        lambda m: f"[{_strip_tags(m[2])}]({m[1]})",
        raw_html,
        flags=re.I,
    )
    text = re.sub(
        r"<h([1-6])[^>]*>([\s\S]*?)</h\1>",
        lambda m: f"\n{'#' * int(m[1])} {_strip_tags(m[2])}\n",
        text,
        flags=re.I,
    )
    text = re.sub(
        r"<li[^>]*>([\s\S]*?)</li>",
        lambda m: f"\n- {_strip_tags(m[1])}",
        text,
        flags=re.I,
    )
    text = re.sub(r"</(p|div|section|article)>", "\n\n", text, flags=re.I)
    text = re.sub(r"<(br|hr)\s*/?>", "\n", text, flags=re.I)
    return _normalize(_strip_tags(text))


# ---------------------------------------------------------------------------
# BrowserSession — persistent browser lifecycle manager
# ---------------------------------------------------------------------------


class BrowserSession:
    """Manages a persistent browser instance across tool calls.

    The browser launches lazily on the first tool call and stays alive
    for the agent session. Cookies, localStorage, and sessionStorage
    persist across calls via a shared BrowserContext.
    """

    def __init__(
        self,
        proxy: str | None = None,
        headless: bool = True,
        timeout: int = 30,
    ):
        """Initialize browser session configuration.

        Args:
            proxy: HTTP/SOCKS5 proxy URL for browser connections.
            headless: Whether to run browser in headless mode.
            timeout: Default navigation timeout in seconds.
        """
        self._playwright: Any = None
        self._browser: Any = None
        self._context: Any = None
        self._page: Any = None
        self.proxy = proxy
        self.headless = headless
        self.timeout = timeout

    async def ensure_page(self) -> Any:
        """Lazy-start: launch browser on first use, reuse thereafter.

        If the browser crashed or was closed, re-launches automatically.

        Returns:
            The active patchright Page object.
        """
        if self._page and not self._page.is_closed():
            return self._page

        # Close stale state if any
        await self._cleanup_stale()

        # Launch fresh
        from patchright.async_api import async_playwright

        self._playwright = await async_playwright().start()
        launch_kwargs: dict[str, Any] = {
            "channel": "chrome",
            "headless": self.headless,
        }
        if self.proxy:
            launch_kwargs["proxy"] = {"server": self.proxy}

        self._browser = await self._playwright.chromium.launch(**launch_kwargs)
        self._context = await self._browser.new_context()
        self._page = await self._context.new_page()
        logger.debug("BrowserSession: launched new browser (headless={})", self.headless)
        return self._page

    async def _cleanup_stale(self) -> None:
        """Close any stale browser/playwright handles."""
        for obj in (self._page, self._context, self._browser):
            if obj:
                try:
                    await obj.close()
                except Exception:
                    pass
        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception:
                pass
        self._page = self._context = self._browser = self._playwright = None

    async def close(self) -> None:
        """Full cleanup -- called from AgentLoop shutdown."""
        await self._cleanup_stale()
        logger.debug("BrowserSession: closed")


# ---------------------------------------------------------------------------
# WebBrowseTool — the agent-facing tool
# ---------------------------------------------------------------------------


class WebBrowseTool(Tool):
    """Browse web pages with a real browser (JavaScript, cookies, sessions).

    The browser persists between calls so the agent can login, navigate,
    and interact across multiple steps like a human.
    """

    name = "web_browse"
    description = (
        "Browse web pages with a real browser (JavaScript, cookies, sessions). "
        "The browser persists between calls -- you can login, navigate, and interact "
        "across multiple steps just like a human. Actions: goto, click, fill, select, "
        "screenshot, evaluate, extract, get_cookies, set_cookies, back, forward, "
        "reload, close."
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "goto",
                    "click",
                    "fill",
                    "select",
                    "screenshot",
                    "evaluate",
                    "extract",
                    "get_cookies",
                    "set_cookies",
                    "back",
                    "forward",
                    "reload",
                    "close",
                ],
                "description": "The browser action to perform",
            },
            "url": {"type": "string", "description": "URL for goto action"},
            "selector": {
                "type": "string",
                "description": "CSS selector for click/fill/select target",
            },
            "text": {
                "type": "string",
                "description": "Text to fill, or value to select",
            },
            "wait_for": {
                "type": "string",
                "description": "CSS selector to wait for after action",
            },
            "extract_mode": {
                "type": "string",
                "enum": ["markdown", "text", "html"],
                "description": "Content format for extract (default: markdown)",
            },
            "javascript": {
                "type": "string",
                "description": "JavaScript code for evaluate action",
            },
            "cookies": {
                "type": "array",
                "items": {"type": "object"},
                "description": "Cookie objects for set_cookies [{name, value, url}]",
            },
        },
        "required": ["action"],
    }

    def __init__(self, session: BrowserSession, max_chars: int = 50000):
        """Initialize the browse tool with a shared browser session.

        Args:
            session: BrowserSession instance (shared across tool calls).
            max_chars: Maximum characters to return in extracted content.
        """
        self.session = session
        self.max_chars = max_chars

    async def execute(
        self,
        action: str,
        url: str | None = None,
        selector: str | None = None,
        text: str | None = None,
        wait_for: str | None = None,
        extract_mode: str = "markdown",
        javascript: str | None = None,
        cookies: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> str:
        """Execute a browser action.

        Args:
            action: The browser action to perform.
            url: URL for goto action.
            selector: CSS selector for click/fill/select.
            text: Text to fill or value to select.
            wait_for: CSS selector to wait for after action.
            extract_mode: Content extraction format.
            javascript: JS code for evaluate action.
            cookies: Cookie objects for set_cookies action.
            **kwargs: Additional parameters (ignored).

        Returns:
            JSON string with action result or error.
        """
        try:
            page = await self.session.ensure_page()
            timeout_ms = self.session.timeout * 1000

            if action == "goto":
                if not url:
                    return json.dumps({"error": "url is required for goto action"})
                await page.goto(url, timeout=timeout_ms, wait_until="networkidle")
                content = await self._extract(page, extract_mode)
                return json.dumps(
                    {
                        "url": str(page.url),
                        "title": await page.title(),
                        "content": content[: self.max_chars],
                        "length": len(content),
                        "truncated": len(content) > self.max_chars,
                    },
                    ensure_ascii=False,
                )

            elif action == "click":
                if not selector:
                    return json.dumps({"error": "selector is required for click action"})
                await page.click(selector, timeout=5000)
                if wait_for:
                    await page.wait_for_selector(wait_for, timeout=5000)
                return json.dumps({"action": "click", "selector": selector, "url": str(page.url)})

            elif action == "fill":
                if not selector or text is None:
                    return json.dumps({"error": "selector and text are required for fill action"})
                await page.fill(selector, text)
                return json.dumps({"action": "fill", "selector": selector})

            elif action == "select":
                if not selector or text is None:
                    return json.dumps({"error": "selector and text are required for select action"})
                await page.select_option(selector, text)
                return json.dumps({"action": "select", "selector": selector, "value": text})

            elif action == "evaluate":
                if not javascript:
                    return json.dumps({"error": "javascript is required for evaluate action"})
                result = await page.evaluate(javascript)
                return json.dumps({"result": result}, ensure_ascii=False, default=str)

            elif action == "get_cookies":
                cookie_list = await page.context.cookies()
                return json.dumps({"cookies": cookie_list}, ensure_ascii=False, default=str)

            elif action == "set_cookies":
                if not cookies:
                    return json.dumps({"error": "cookies array is required for set_cookies action"})
                await page.context.add_cookies(cookies)
                return json.dumps({"status": "cookies_set", "count": len(cookies)})

            elif action == "screenshot":
                # Save screenshot to the workspace directory with an absolute path
                import os

                workspace = os.environ.get(
                    "VELO_WORKSPACE", os.path.expanduser("~/.velo/workspace")
                )
                safe_name = re.sub(r"[^a-zA-Z0-9]", "_", str(page.url))[:50]
                path = os.path.join(workspace, f"{safe_name}.png")
                await page.screenshot(path=path)
                return json.dumps({"path": path, "url": str(page.url)})

            elif action == "extract":
                content = await self._extract(page, extract_mode)
                return json.dumps(
                    {
                        "url": str(page.url),
                        "title": await page.title(),
                        "content": content[: self.max_chars],
                        "length": len(content),
                        "truncated": len(content) > self.max_chars,
                    },
                    ensure_ascii=False,
                )

            elif action == "back":
                await page.go_back()
                return json.dumps({"action": "back", "url": str(page.url)})

            elif action == "forward":
                await page.go_forward()
                return json.dumps({"action": "forward", "url": str(page.url)})

            elif action == "reload":
                await page.reload()
                return json.dumps({"action": "reload", "url": str(page.url)})

            elif action == "close":
                await self.session.close()
                return json.dumps({"status": "browser_closed"})

            else:
                return json.dumps({"error": f"Unknown action: {action}"})

        except Exception as e:
            logger.error("WebBrowse error (action={}): {}", action, e)
            return json.dumps({"error": str(e), "action": action})

    async def _extract(self, page: Any, mode: str) -> str:
        """Extract page content in the requested format.

        Args:
            page: Patchright Page object.
            mode: Extraction mode ('markdown', 'text', or 'html').

        Returns:
            Extracted content string.
        """
        raw_html = await page.content()

        if mode == "html":
            return raw_html

        from readability import Document

        doc = Document(raw_html)
        summary = doc.summary()
        title = doc.title()

        if mode == "text":
            body = _strip_tags(summary)
            return f"{title}\n\n{body}" if title else body

        # mode == "markdown"
        content = _html_to_markdown(summary)
        return f"# {title}\n\n{content}" if title else content
