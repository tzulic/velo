"""Tests for plugin HTTP route system."""

from __future__ import annotations

import pytest

from velo.plugins.http import RouteTable
from velo.plugins.types import HttpRequest, HttpResponse


class TestRouteTable:
    def test_register_route(self) -> None:
        rt = RouteTable()

        async def handler(req: HttpRequest) -> HttpResponse:
            return HttpResponse(status=200)

        rt.register("POST", "/webhooks/stripe", handler, plugin_name="test")
        assert rt.has_routes()

    def test_collision_detection(self) -> None:
        rt = RouteTable()

        async def handler(req: HttpRequest) -> HttpResponse:
            return HttpResponse(status=200)

        rt.register("POST", "/webhooks/stripe", handler, plugin_name="a")
        with pytest.raises(ValueError, match="already registered"):
            rt.register("POST", "/webhooks/stripe", handler, plugin_name="b")

    def test_different_methods_no_collision(self) -> None:
        rt = RouteTable()

        async def handler(req: HttpRequest) -> HttpResponse:
            return HttpResponse(status=200)

        rt.register("POST", "/webhooks/stripe", handler, plugin_name="a")
        rt.register("GET", "/webhooks/stripe", handler, plugin_name="a")
        assert rt.has_routes()

    async def test_dispatch(self) -> None:
        rt = RouteTable()

        async def handler(req: HttpRequest) -> HttpResponse:
            return HttpResponse(status=200, body=f"got {req.path}")

        rt.register("POST", "/webhooks/test", handler, plugin_name="test")
        req = HttpRequest(
            method="POST",
            path="/plugins/webhooks/test",
            body=b"",
            headers={},
            query_params={},
        )
        resp = await rt.dispatch(req)
        assert resp.status == 200
        assert "got" in str(resp.body)

    async def test_dispatch_not_found(self) -> None:
        rt = RouteTable()
        req = HttpRequest(
            method="GET",
            path="/plugins/unknown",
            body=b"",
            headers={},
            query_params={},
        )
        resp = await rt.dispatch(req)
        assert resp.status == 404

    def test_empty_table(self) -> None:
        rt = RouteTable()
        assert not rt.has_routes()

    async def test_handler_exception_returns_500(self) -> None:
        rt = RouteTable()

        async def bad_handler(req: HttpRequest) -> HttpResponse:
            raise RuntimeError("boom")

        rt.register("POST", "/crash", bad_handler, plugin_name="test")
        req = HttpRequest(
            method="POST",
            path="/plugins/crash",
            body=b"",
            headers={},
            query_params={},
        )
        resp = await rt.dispatch(req)
        assert resp.status == 500
