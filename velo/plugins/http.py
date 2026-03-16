"""Plugin HTTP route system.

RouteTable collects plugin-registered routes. PluginHttpServer serves them
on the gateway port using aiohttp.
"""

from __future__ import annotations

from typing import Awaitable, Callable

from aiohttp import web
from loguru import logger

from velo.plugins.types import HttpRequest, HttpResponse

RouteHandler = Callable[[HttpRequest], Awaitable[HttpResponse]]

_PLUGIN_PREFIX = "/plugins"


class RouteTable:
    """Stores plugin HTTP routes and dispatches requests.

    Routes are keyed by (method, path) tuples. Each entry stores the handler
    and the owning plugin name for error reporting.
    """

    def __init__(self) -> None:
        self._routes: dict[tuple[str, str], tuple[RouteHandler, str]] = {}

    def register(
        self,
        method: str,
        path: str,
        handler: RouteHandler,
        plugin_name: str,
    ) -> None:
        """Register a route. Raises ValueError on collision.

        Args:
            method: HTTP method (POST, GET, etc.).
            path: URL path (without /plugins/ prefix).
            handler: Async handler function.
            plugin_name: Owning plugin name for error messages.

        Raises:
            ValueError: If a route with the same method and path is already registered.
        """
        key = (method.upper(), path)
        if key in self._routes:
            existing_plugin = self._routes[key][1]
            raise ValueError(
                f"Route {method} {path} already registered by plugin '{existing_plugin}'"
            )
        self._routes[key] = (handler, plugin_name)

    def has_routes(self) -> bool:
        """Return True if any routes are registered.

        Returns:
            True if at least one route has been registered.
        """
        return len(self._routes) > 0

    async def dispatch(self, request: HttpRequest) -> HttpResponse:
        """Dispatch a request to the matching handler.

        Strips the /plugins prefix from the path before lookup so routes
        can be registered without the prefix.

        Args:
            request: The incoming HTTP request.

        Returns:
            HttpResponse from the handler, or 404 if no match found,
            or 500 if the handler raises an exception.
        """
        path = request.path
        if path.startswith(_PLUGIN_PREFIX):
            # Reason: routes are registered without the /plugins prefix,
            # but requests arrive with it from the aiohttp router.
            path = path[len(_PLUGIN_PREFIX) :]

        key = (request.method.upper(), path)
        entry = self._routes.get(key)
        if entry is None:
            return HttpResponse(status=404, body="Not found")

        handler, plugin_name = entry
        try:
            return await handler(request)
        except Exception:
            logger.exception("plugin.http_handler_failed: {} {}", request.method, path)
            return HttpResponse(status=500, body="Internal server error")


class PluginHttpServer:
    """Lightweight aiohttp server for plugin routes.

    Binds to the gateway port and forwards all ``/plugins/{path}`` requests
    to the RouteTable for dispatch.

    Args:
        route_table: The route table with registered handlers.
        host: Bind host. Default "0.0.0.0".
        port: Bind port. Default 18790.
    """

    def __init__(
        self,
        route_table: RouteTable,
        host: str = "0.0.0.0",
        port: int = 18790,
    ) -> None:
        self._route_table = route_table
        self._host = host
        self._port = port
        self._runner: web.AppRunner | None = None

    async def start(self) -> None:
        """Start the HTTP server.

        Creates an aiohttp application, registers a catch-all route under
        /plugins/, and begins serving requests.
        """
        app = web.Application()
        app.router.add_route("*", "/plugins/{path:.*}", self._handle)
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self._host, self._port)
        await site.start()
        logger.info("plugin.http_server_started: {}:{}", self._host, self._port)

    async def stop(self) -> None:
        """Stop the HTTP server and clean up the runner."""
        if self._runner:
            await self._runner.cleanup()
            logger.info("plugin.http_server_stopped")

    async def _handle(self, request: web.Request) -> web.Response:
        """aiohttp handler that bridges to RouteTable.

        Reads the raw request body, converts to an HttpRequest, dispatches
        through the RouteTable, and maps the result back to a web.Response.

        Args:
            request: The aiohttp request object.

        Returns:
            aiohttp web.Response built from the plugin handler's HttpResponse.
        """
        body = await request.read()
        plugin_req = HttpRequest(
            method=request.method,
            path=request.path,
            body=body,
            headers=dict(request.headers),
            query_params=dict(request.query),
        )
        plugin_resp = await self._route_table.dispatch(plugin_req)
        # Reason: aiohttp web.Response expects body as bytes; convert str if needed.
        response_body: bytes
        if isinstance(plugin_resp.body, str):
            response_body = plugin_resp.body.encode()
        else:
            response_body = plugin_resp.body
        return web.Response(
            status=plugin_resp.status,
            body=response_body,
            headers=plugin_resp.headers,
        )
