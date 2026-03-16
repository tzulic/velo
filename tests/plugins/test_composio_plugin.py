"""Tests for the Composio builtin plugin."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from velo.plugins.builtin.composio.wrapper import ComposioToolWrapper
from velo.plugins.types import PluginContext

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

SAMPLE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "GMAIL_SEND_EMAIL",
            "description": "Send an email using Gmail",
            "parameters": {
                "type": "object",
                "properties": {
                    "to": {"type": "string"},
                    "body": {"type": "string"},
                },
                "required": ["to", "body"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "GMAIL_LIST_EMAILS",
            "description": "List emails from Gmail inbox",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]


def _mock_composio(tools: list | None = None):
    """Create a mock Composio client + session returning given tool defs."""
    session = MagicMock()
    session.tools.return_value = tools if tools is not None else SAMPLE_TOOLS

    client = MagicMock()
    client.create.return_value = session

    return client


def _make_wrapper(**overrides) -> ComposioToolWrapper:
    """Create a ComposioToolWrapper with sensible defaults."""
    defaults = {
        "composio_client": MagicMock(),
        "user_id": "test-user-123",
        "slug": "GMAIL_SEND_EMAIL",
        "description": "Send an email using Gmail",
        "input_parameters": {
            "type": "object",
            "properties": {"to": {"type": "string"}},
        },
    }
    defaults.update(overrides)
    return ComposioToolWrapper(**defaults)


# ---------------------------------------------------------------------------
# Plugin register()/activate() tests
# ---------------------------------------------------------------------------


class TestComposioPluginSetup:
    """Tests for the composio plugin register()/activate() entry points."""

    @pytest.mark.asyncio
    @patch.dict("os.environ", {"COMPOSIO_API_KEY": "sk-test", "COMPOSIO_USER_ID": "u1"})
    @patch("velo.plugins.builtin.composio.Composio")
    async def test_setup_registers_tools(self, mock_composio_cls) -> None:
        """activate() registers deferred tools for each connected toolkit tool."""
        mock_composio_cls.return_value = _mock_composio()

        from velo.plugins.builtin.composio import activate, register

        ctx = PluginContext("composio", {}, Path("/tmp"))
        register(ctx)
        await activate(ctx)

        tools = ctx._collect_tools()
        assert len(tools) == 2
        # All tools must be deferred
        assert all(deferred for _, deferred in tools)
        names = [t.name for t, _ in tools]
        assert "composio_gmail_send_email" in names
        assert "composio_gmail_list_emails" in names

    @pytest.mark.asyncio
    @patch.dict("os.environ", {}, clear=True)
    async def test_setup_missing_env_vars(self) -> None:
        """No env vars → no tools registered, no crash."""
        from velo.plugins.builtin.composio import activate, register

        ctx = PluginContext("composio", {}, Path("/tmp"))
        register(ctx)
        await activate(ctx)

        assert len(ctx._collect_tools()) == 0

    @pytest.mark.asyncio
    @patch.dict("os.environ", {"COMPOSIO_API_KEY": "", "COMPOSIO_USER_ID": "u1"})
    async def test_setup_empty_api_key(self) -> None:
        """Empty API key → skip gracefully."""
        from velo.plugins.builtin.composio import activate, register

        ctx = PluginContext("composio", {}, Path("/tmp"))
        register(ctx)
        await activate(ctx)

        assert len(ctx._collect_tools()) == 0

    @pytest.mark.asyncio
    @patch.dict("os.environ", {"COMPOSIO_API_KEY": "sk-test", "COMPOSIO_USER_ID": "u1"})
    @patch("velo.plugins.builtin.composio.Composio")
    async def test_setup_sdk_error(self, mock_composio_cls) -> None:
        """SDK throws → log warning, no crash, no tools."""
        mock_composio_cls.side_effect = RuntimeError("connection failed")

        from velo.plugins.builtin.composio import activate, register

        ctx = PluginContext("composio", {}, Path("/tmp"))
        register(ctx)
        await activate(ctx)

        assert len(ctx._collect_tools()) == 0

    @pytest.mark.asyncio
    @patch.dict("os.environ", {"COMPOSIO_API_KEY": "sk-test", "COMPOSIO_USER_ID": "u1"})
    @patch("velo.plugins.builtin.composio.Composio")
    async def test_setup_empty_tools(self, mock_composio_cls) -> None:
        """No connected toolkits → zero tools, no crash."""
        mock_composio_cls.return_value = _mock_composio(tools=[])

        from velo.plugins.builtin.composio import activate, register

        ctx = PluginContext("composio", {}, Path("/tmp"))
        register(ctx)
        await activate(ctx)

        assert len(ctx._collect_tools()) == 0

    @pytest.mark.asyncio
    @patch.dict("os.environ", {"COMPOSIO_API_KEY": "sk-test", "COMPOSIO_USER_ID": "u1"})
    @patch("velo.plugins.builtin.composio.Composio")
    async def test_setup_handles_raw_tool_objects(self, mock_composio_cls) -> None:
        """Handles raw Composio Tool objects (not dicts) gracefully."""
        raw_tool = MagicMock()
        raw_tool.slug = "SLACK_SEND_MESSAGE"
        raw_tool.description = "Send a Slack message"
        raw_tool.input_parameters = {"type": "object", "properties": {}}
        # Make it not a dict so isinstance(tool_def, dict) is False
        raw_tool.__class__ = type("ComposioTool", (), {})

        client = _mock_composio(tools=[raw_tool])
        mock_composio_cls.return_value = client

        from velo.plugins.builtin.composio import activate, register

        ctx = PluginContext("composio", {}, Path("/tmp"))
        register(ctx)
        await activate(ctx)

        tools = ctx._collect_tools()
        assert len(tools) == 1
        assert tools[0][0].name == "composio_slack_send_message"

    @pytest.mark.asyncio
    @patch.dict("os.environ", {"COMPOSIO_API_KEY": "sk-test", "COMPOSIO_USER_ID": "u1"})
    @patch("velo.plugins.builtin.composio.Composio")
    async def test_setup_skips_nameless_tools(self, mock_composio_cls) -> None:
        """Tools with no name are skipped with a warning, not registered as 'unknown'."""
        nameless_tool = {"type": "function", "function": {"description": "no name here"}}
        valid_tool = SAMPLE_TOOLS[0]

        mock_composio_cls.return_value = _mock_composio(tools=[nameless_tool, valid_tool])

        from velo.plugins.builtin.composio import activate, register

        ctx = PluginContext("composio", {}, Path("/tmp"))
        register(ctx)
        await activate(ctx)

        tools = ctx._collect_tools()
        assert len(tools) == 1
        assert tools[0][0].name == "composio_gmail_send_email"


# ---------------------------------------------------------------------------
# Wrapper property tests
# ---------------------------------------------------------------------------


class TestComposioToolWrapperProperties:
    """Tests for ComposioToolWrapper name/description/parameters."""

    def test_name_is_prefixed_and_lowered(self) -> None:
        """Tool name is composio_{slug_lowered}."""
        wrapper = _make_wrapper(slug="GMAIL_SEND_EMAIL")
        assert wrapper.name == "composio_gmail_send_email"

    def test_description_passthrough(self) -> None:
        """Description is passed through as-is."""
        wrapper = _make_wrapper(description="Send an email")
        assert wrapper.description == "Send an email"

    def test_parameters_passthrough(self) -> None:
        """Parameters schema is passed through as-is."""
        params = {"type": "object", "properties": {"to": {"type": "string"}}}
        wrapper = _make_wrapper(input_parameters=params)
        assert wrapper.parameters == params

    def test_to_schema_openai_format(self) -> None:
        """to_schema() returns OpenAI function call format."""
        wrapper = _make_wrapper()
        schema = wrapper.to_schema()
        assert schema["type"] == "function"
        assert schema["function"]["name"] == "composio_gmail_send_email"


# ---------------------------------------------------------------------------
# Wrapper execute() tests
# ---------------------------------------------------------------------------


class TestComposioToolWrapperExecute:
    """Tests for ComposioToolWrapper.execute()."""

    @pytest.mark.asyncio
    async def test_execute_success(self) -> None:
        """Successful execution returns data string."""
        client = MagicMock()
        client.tools.execute.return_value = {
            "successful": True,
            "data": {"message_id": "abc123"},
        }

        wrapper = _make_wrapper(composio_client=client, user_id="u1")
        result = await wrapper.execute(to="alice@example.com", body="Hello")

        client.tools.execute.assert_called_once_with(
            "GMAIL_SEND_EMAIL",
            {"to": "alice@example.com", "body": "Hello"},
            user_id="u1",
        )
        assert "abc123" in result

    @pytest.mark.asyncio
    async def test_execute_tool_error(self) -> None:
        """Tool returns unsuccessful result."""
        client = MagicMock()
        client.tools.execute.return_value = {
            "successful": False,
            "error": "auth_expired",
        }

        wrapper = _make_wrapper(composio_client=client)
        result = await wrapper.execute(to="x@x.com")
        assert "tool error" in result
        assert "auth_expired" in result

    @pytest.mark.asyncio
    async def test_execute_timeout(self) -> None:
        """Execution exceeding timeout returns timeout message."""
        client = MagicMock()

        async def _slow(*args, **kwargs):
            await AsyncMock(side_effect=TimeoutError)()

        with patch("asyncio.wait_for", side_effect=TimeoutError):
            wrapper = _make_wrapper(composio_client=client, timeout=1)
            result = await wrapper.execute(to="x@x.com")

        assert "timed out" in result

    @pytest.mark.asyncio
    async def test_execute_exception(self) -> None:
        """Unexpected exception returns error message."""
        client = MagicMock()
        client.tools.execute.side_effect = ConnectionError("network failure")

        wrapper = _make_wrapper(composio_client=client)
        result = await wrapper.execute(to="x@x.com")
        assert "ConnectionError" in result

    @pytest.mark.asyncio
    async def test_execute_raw_string_result(self) -> None:
        """Non-dict result is stringified."""
        client = MagicMock()
        client.tools.execute.return_value = "raw output"

        wrapper = _make_wrapper(composio_client=client)
        result = await wrapper.execute(to="x@x.com")
        assert result == "raw output"

    @pytest.mark.asyncio
    async def test_execute_no_data_key(self) -> None:
        """Successful result with no data key returns '(no output)'."""
        client = MagicMock()
        client.tools.execute.return_value = {"successful": True}

        wrapper = _make_wrapper(composio_client=client)
        result = await wrapper.execute()
        assert result == "(no output)"
