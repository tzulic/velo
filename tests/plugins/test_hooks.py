"""Tests for expanded hook system."""

from pathlib import Path

from velo.plugins.types import HOOKS, HttpRequest, HttpResponse, PluginContext


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
