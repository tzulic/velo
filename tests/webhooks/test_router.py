"""Tests for webhook routing."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from velo.config.schema import WebhookBindingConfig, WebhooksConfig
from velo.webhooks.router import WebhookRouter


class TestWebhookRouter:
    def _make_router(self, bindings):
        config = WebhooksConfig(enabled=True, bindings=bindings)
        bus = AsyncMock()
        return WebhookRouter(config=config, bus=bus)

    @pytest.mark.asyncio
    async def test_path_matching(self):
        binding = WebhookBindingConfig(name="stripe", path="/hooks/stripe")
        router = self._make_router([binding])
        result = await router.handle("/hooks/stripe", b'{"event": "paid"}', {})
        assert result["status"] == "ok"
        router._bus.publish_inbound.assert_called_once()

    @pytest.mark.asyncio
    async def test_unknown_path_returns_404(self):
        router = self._make_router([])
        result = await router.handle("/hooks/unknown", b"{}", {})
        assert result["status"] == "not_found"

    @pytest.mark.asyncio
    async def test_payload_template_rendering(self):
        binding = WebhookBindingConfig(
            name="test", path="/hooks/test", template="Received: {payload}"
        )
        router = self._make_router([binding])
        await router.handle("/hooks/test", b'{"amount": 100}', {})
        call_args = router._bus.publish_inbound.call_args
        msg = call_args[0][0]
        assert "Received:" in msg.content
        assert "100" in msg.content

    @pytest.mark.asyncio
    async def test_signature_verification_rejects_bad_sig(self):
        binding = WebhookBindingConfig(name="signed", path="/hooks/signed", secret="my-secret")
        router = self._make_router([binding])
        result = await router.handle("/hooks/signed", b"payload", {"x-signature": "bad"})
        assert result["status"] == "unauthorized"
