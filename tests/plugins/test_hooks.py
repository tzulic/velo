"""Tests for expanded hook system."""

import pytest
from pathlib import Path
from unittest.mock import AsyncMock

from velo.plugins.manager import PluginManager
from velo.plugins.types import HOOKS, HookEntry, HttpRequest, HttpResponse, PluginContext


class TestHookDefinitions:
    """Verify all 18 hooks are defined with correct strategies."""

    def test_hook_count(self):
        assert len(HOOKS) == 18

    def test_fire_and_forget_hooks(self):
        expected = {
            "on_startup", "on_shutdown", "message_received", "message_sent",
            "agent_end", "before_reset", "session_start", "session_end",
            "subagent_spawned", "subagent_ended",
        }
        actual = {name for name, typ in HOOKS.items() if typ == "fire_and_forget"}
        assert actual == expected

    def test_modifying_hooks(self):
        expected = {
            "before_model_resolve", "before_prompt_build", "after_prompt_build",
            "before_tool_call", "after_tool_call", "message_sending",
            "before_message_write",
        }
        actual = {name for name, typ in HOOKS.items() if typ == "modifying"}
        assert actual == expected

    def test_claiming_hooks(self):
        expected = {"inbound_claim"}
        actual = {name for name, typ in HOOKS.items() if typ == "claiming"}
        assert actual == expected

    def test_before_response_removed(self):
        assert "before_response" not in HOOKS

    def test_hook_type_literal(self):
        valid_types = {"fire_and_forget", "modifying", "claiming"}
        for name, typ in HOOKS.items():
            assert typ in valid_types, f"Hook '{name}' has invalid type '{typ}'"


class TestPluginContextDisable:
    def test_disable_sets_flag(self):
        ctx = PluginContext(plugin_name="test", config={}, workspace=Path("/tmp"))
        assert not ctx._disabled
        ctx.disable("missing api_key")
        assert ctx._disabled
        assert ctx._disable_reason == "missing api_key"

    def test_not_disabled_by_default(self):
        ctx = PluginContext(plugin_name="test", config={}, workspace=Path("/tmp"))
        assert not ctx._disabled
        assert ctx._disable_reason == ""


class TestPluginContextHttpRoutes:
    def test_register_route(self):
        ctx = PluginContext(plugin_name="test", config={}, workspace=Path("/tmp"))

        async def handler(req: HttpRequest) -> HttpResponse:
            return HttpResponse(status=200, body="ok")

        ctx.register_http_route(method="POST", path="/webhooks/test", handler=handler)
        routes = ctx._collect_http_routes()
        assert len(routes) == 1
        assert routes[0]["method"] == "POST"
        assert routes[0]["path"] == "/webhooks/test"

    def test_collect_empty_routes(self):
        ctx = PluginContext(plugin_name="test", config={}, workspace=Path("/tmp"))
        assert ctx._collect_http_routes() == []


class TestHttpTypes:
    def test_http_request_fields(self):
        req = HttpRequest(method="POST", path="/test", body=b"hello", headers={}, query_params={})
        assert req.method == "POST"
        assert req.body == b"hello"

    def test_http_response_defaults(self):
        resp = HttpResponse()
        assert resp.status == 200
        assert resp.body == ""
        assert resp.headers == {}


class TestClaimDispatch:
    """Test claiming hook dispatch."""

    def _make_manager(self) -> PluginManager:
        mgr = PluginManager(workspace=Path("/tmp"), config={})
        mgr._loaded = True
        return mgr

    @pytest.mark.asyncio
    async def test_claim_returns_first_truthy(self):
        mgr = self._make_manager()
        mgr._hooks["inbound_claim"] = [
            HookEntry(callback=AsyncMock(return_value=None), priority=100),
            HookEntry(callback=AsyncMock(return_value={"handled": True}), priority=200),
            HookEntry(callback=AsyncMock(return_value={"handled": True}), priority=300),
        ]
        result = await mgr.claim("inbound_claim", content="hi", channel="telegram", chat_id="123")
        assert result == {"handled": True}
        mgr._hooks["inbound_claim"][2].callback.assert_not_called()

    @pytest.mark.asyncio
    async def test_claim_returns_none_when_no_claim(self):
        mgr = self._make_manager()
        mgr._hooks["inbound_claim"] = [
            HookEntry(callback=AsyncMock(return_value=None), priority=100),
        ]
        result = await mgr.claim("inbound_claim", content="hi", channel="telegram", chat_id="123")
        assert result is None

    @pytest.mark.asyncio
    async def test_claim_error_isolation(self):
        mgr = self._make_manager()
        mgr._hooks["inbound_claim"] = [
            HookEntry(callback=AsyncMock(side_effect=RuntimeError("boom")), priority=100),
            HookEntry(callback=AsyncMock(return_value={"handled": True}), priority=200),
        ]
        result = await mgr.claim("inbound_claim", content="hi", channel="telegram", chat_id="123")
        assert result == {"handled": True}


class TestPipeCancelBlock:
    """Test pipe() cancel/block short-circuit."""

    def _make_manager(self) -> PluginManager:
        mgr = PluginManager(workspace=Path("/tmp"), config={})
        mgr._loaded = True
        return mgr

    @pytest.mark.asyncio
    async def test_pipe_cancel_short_circuits(self):
        mgr = self._make_manager()
        second_cb = AsyncMock(return_value="should not run")
        mgr._hooks["message_sending"] = [
            HookEntry(callback=AsyncMock(return_value={"cancel": True}), priority=100),
            HookEntry(callback=second_cb, priority=200),
        ]
        result = await mgr.pipe("message_sending", value="hello", channel="telegram", chat_id="123")
        assert result == {"cancel": True}
        second_cb.assert_not_called()

    @pytest.mark.asyncio
    async def test_pipe_block_short_circuits(self):
        mgr = self._make_manager()
        mgr._hooks["before_tool_call"] = [
            HookEntry(callback=AsyncMock(return_value={"__block": True}), priority=100),
        ]
        result = await mgr.pipe("before_tool_call", value={"cmd": "rm -rf /"}, tool_name="exec")
        assert result == {"__block": True}

    @pytest.mark.asyncio
    async def test_pipe_passthrough_unchanged(self):
        mgr = self._make_manager()
        mgr._hooks["after_prompt_build"] = [
            HookEntry(callback=AsyncMock(return_value=None), priority=100),
        ]
        result = await mgr.pipe("after_prompt_build", value="original prompt")
        assert result == "original prompt"
