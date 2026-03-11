"""Webhook receiver plugin — HTTP server that injects incoming webhooks as agent messages.

Starts an aiohttp server on a configurable port. Each route can optionally
verify HMAC-SHA256 signatures for Stripe, Shopify, or generic services.

Config keys:
    port (int): HTTP port to bind. Default 8090.
    routes (list[dict]): Each entry: path, service, secret_env.
    max_events_log (int): In-memory event log size. Default 100.
    reject_invalid_signatures (bool): Return 401 on invalid sig. Default False.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import os
from collections import deque
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from velo.agent.tools.base import Tool
from velo.plugins.types import PluginContext, RuntimeRefs

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Signature verification helpers
# ---------------------------------------------------------------------------


def _verify_stripe(raw_body: bytes, header: str, secret: str) -> bool:
    """Verify Stripe webhook: t=<ts>,v1=<hex> signed over '{ts}.{body}'."""
    try:
        parts = dict(p.split("=", 1) for p in header.split(","))
        payload = f"{parts.get('t', '')}.".encode() + raw_body
        expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, parts.get("v1", ""))
    except Exception:
        return False


def _verify_shopify(raw_body: bytes, header: str, secret: str) -> bool:
    """Verify Shopify webhook: base64(HMAC-SHA256(body, client_secret))."""
    try:
        digest = hmac.new(secret.encode(), raw_body, hashlib.sha256).digest()
        return hmac.compare_digest(base64.b64encode(digest).decode(), header.strip())
    except Exception:
        return False


def _verify_generic(raw_body: bytes, header: str, secret: str) -> bool:
    """Verify generic webhook: hex(HMAC-SHA256(body, secret))."""
    try:
        expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, header.strip())
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Webhook server
# ---------------------------------------------------------------------------


class _WebhookServer:
    """aiohttp webhook receiver service (ServiceLike + RuntimeAware).

    Args:
        port: HTTP port to bind.
        routes: List of route config dicts (path, service, secret_env).
        max_events: Maximum in-memory event log size.
        reject_invalid: Return 401 on invalid signatures when True.
    """

    def __init__(
        self,
        port: int,
        routes: list[dict[str, Any]],
        max_events: int,
        reject_invalid: bool,
    ) -> None:
        self._port = port
        self._routes = routes
        self._reject_invalid = reject_invalid
        self._process_direct: Callable[..., Awaitable[str]] | None = None
        self._event_log: deque[dict[str, Any]] = deque(maxlen=max_events)
        self._runner: Any = None  # aiohttp.web.AppRunner

    def set_runtime(self, refs: RuntimeRefs) -> None:
        """Store process_direct for injecting webhook events to the agent.

        Args:
            refs: Late-bound runtime references.
        """
        self._process_direct = refs.process_direct

    async def start(self) -> None:
        """Build aiohttp app and start listening."""
        try:
            from aiohttp import web
        except ImportError:
            logger.error("webhook_receiver.aiohttp_unavailable: install aiohttp")
            return
        app = web.Application()
        for route_cfg in self._routes:
            path = route_cfg.get("path", "/webhooks/default")
            app.router.add_post(path, self._make_handler(route_cfg))
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "0.0.0.0", self._port)
        try:
            await site.start()
            logger.info("webhook_receiver.started: port=%d", self._port)
        except OSError as exc:
            logger.error("webhook_receiver.start_failed: port=%d error=%s", self._port, exc)
            await self._runner.cleanup()
            self._runner = None

    def stop(self) -> None:
        """Schedule aiohttp runner cleanup."""
        if self._runner:
            asyncio.create_task(self._runner.cleanup())
            self._runner = None

    def _make_handler(self, route_cfg: dict[str, Any]) -> Any:
        """Return an aiohttp handler closure for a route."""
        async def handler(request: Any) -> Any:
            return await self._handle(request, route_cfg)
        return handler

    async def _handle(self, request: Any, route_cfg: dict[str, Any]) -> Any:
        """Process an incoming webhook request.

        Verifies signature if configured, parses JSON body, logs the event,
        and injects it to the agent via process_direct.

        Args:
            request: aiohttp Request.
            route_cfg: Route config dict.

        Returns:
            aiohttp Response (200 OK or 401).
        """
        from aiohttp import web

        service = route_cfg.get("service", "unknown")
        path = route_cfg.get("path", "/webhooks/default")
        secret_env = route_cfg.get("secret_env", "")
        raw_body = await request.read()

        if secret_env:
            secret = os.environ.get(secret_env, "")
            if secret:
                if not self._verify_sig(service, raw_body, request.headers, secret):
                    logger.warning(
                        "webhook_receiver.invalid_signature: service=%s path=%s", service, path
                    )
                    if self._reject_invalid:
                        return web.Response(status=401, text="Invalid signature")
            else:
                logger.warning("webhook_receiver.secret_env_unset: env=%s", secret_env)

        try:
            parsed: dict[str, Any] = json.loads(raw_body)
        except (json.JSONDecodeError, ValueError):
            parsed = {}
            logger.warning(
                "webhook_receiver.invalid_json: service=%s body=%s", service, raw_body[:80]
            )

        event: dict[str, Any] = {
            "service": service,
            "path": path,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": parsed,
        }
        self._event_log.append(event)
        await self._inject_to_agent(event)
        return web.Response(status=200, text="OK")

    def _verify_sig(
        self, service: str, raw_body: bytes, headers: Any, secret: str
    ) -> bool:
        """Route to the correct signature verifier based on service name."""
        if service == "stripe":
            return _verify_stripe(raw_body, headers.get("Stripe-Signature", ""), secret)
        if service == "shopify":
            return _verify_shopify(raw_body, headers.get("X-Shopify-Hmac-Sha256", ""), secret)
        return _verify_generic(raw_body, headers.get("X-Webhook-Signature", ""), secret)

    async def _inject_to_agent(self, event: dict[str, Any]) -> None:
        """Send webhook event to the agent; buffer in log if process_direct unavailable."""
        if self._process_direct is None:
            logger.debug("webhook_receiver.buffered: process_direct not available yet")
            return
        payload_str = json.dumps(event["payload"])[:2000]
        message = (
            f"Webhook received from {event['service']} ({event['path']}) "
            f"at {event['timestamp']}:\n{payload_str}"
        )
        try:
            await self._process_direct(
                message, session_key="webhook", channel="cli", chat_id="webhook"
            )
        except Exception:
            logger.exception("webhook_receiver.inject_failed")

    def get_event_log(self) -> list[dict[str, Any]]:
        """Return a copy of the in-memory event log (oldest first)."""
        return list(self._event_log)


# ---------------------------------------------------------------------------
# Tool
# ---------------------------------------------------------------------------


class ListWebhookEventsTool(Tool):
    """Tool: list recent webhook events received by the server."""

    def __init__(self, server: _WebhookServer) -> None:
        self._server = server

    @property
    def name(self) -> str:
        return "list_webhook_events"

    @property
    def description(self) -> str:
        return "List recent webhook events received by the webhook receiver."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "default": 10,
                    "description": "Number of most recent events to return",
                }
            },
            "required": [],
        }

    async def execute(self, **kwargs: Any) -> str:
        """Return a summary of recent webhook events."""
        limit = int(kwargs.get("limit", 10))
        events = self._server.get_event_log()
        recent = events[-limit:] if len(events) > limit else events
        if not recent:
            return "No webhook events received yet."
        lines = [f"Recent {len(recent)} webhook event(s):\n"]
        for ev in recent:
            lines.append(f"  [{ev['timestamp']}] {ev['service']} {ev['path']}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Plugin entry point
# ---------------------------------------------------------------------------


def setup(ctx: PluginContext) -> None:
    """Plugin entry point — register webhook server and tool.

    Args:
        ctx: Plugin context with config and workspace.
    """
    server = _WebhookServer(
        port=int(ctx.config.get("port", 8090)),
        routes=ctx.config.get("routes", []),
        max_events=int(ctx.config.get("max_events_log", 100)),
        reject_invalid=bool(ctx.config.get("reject_invalid_signatures", False)),
    )
    ctx.register_service(server)
    ctx.register_tool(ListWebhookEventsTool(server))
    logger.debug("webhook_receiver.setup_completed: port=%d", ctx.config.get("port", 8090))
