"""HTTP handler for incoming webhooks, routes to agent sessions."""

from __future__ import annotations

import hashlib
import hmac
from typing import Any

from loguru import logger

from velo.bus.events import InboundMessage
from velo.bus.queue import MessageBus
from velo.config.schema import WebhookBindingConfig, WebhooksConfig


class WebhookRouter:
    """Routes incoming webhook payloads to agent sessions via the message bus.

    Args:
        config: Webhooks configuration with bindings.
        bus: Message bus for publishing inbound messages.
    """

    def __init__(self, config: WebhooksConfig, bus: MessageBus) -> None:
        self._config = config
        self._bus = bus
        self._bindings: dict[str, WebhookBindingConfig] = {b.path: b for b in config.bindings}

    async def handle(self, path: str, body: bytes, headers: dict[str, str]) -> dict[str, Any]:
        """Match path to binding, verify signature, publish to bus.

        Args:
            path: URL path of the incoming request.
            body: Raw request body.
            headers: Request headers.

        Returns:
            dict: Response with status key.
        """
        binding = self._bindings.get(path)
        if binding is None:
            return {"status": "not_found"}

        if binding.secret:
            sig_header = headers.get("x-signature", "") or headers.get("x-hub-signature-256", "")
            expected = hmac.new(binding.secret.encode(), body, hashlib.sha256).hexdigest()
            sig_clean = sig_header.replace("sha256=", "")
            if not hmac.compare_digest(sig_clean, expected):
                logger.warning("webhook.signature_rejected: path={} name={}", path, binding.name)
                return {"status": "unauthorized"}

        try:
            payload_str = body.decode("utf-8")
        except UnicodeDecodeError:
            payload_str = body.hex()

        content = binding.template.replace("{payload}", payload_str)
        session_key = binding.session_key or f"webhook:{binding.name}"

        msg = InboundMessage(
            channel="webhook",
            sender_id="webhook",
            chat_id=session_key,
            content=content,
            media=[],
            metadata={"webhook_name": binding.name, "webhook_path": path},
        )
        await self._bus.publish_inbound(msg)
        logger.info("webhook.routed: name={} path={}", binding.name, path)
        return {"status": "ok"}
