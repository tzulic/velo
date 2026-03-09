"""Tests for the heartbeat builtin plugin."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.plugins.types import PluginContext, RuntimeRefs


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_refs(**overrides) -> RuntimeRefs:
    defaults = {
        "provider": MagicMock(),
        "model": "test-model",
        "bus": MagicMock(),
        "process_direct": AsyncMock(return_value="done"),
        "publish_outbound": AsyncMock(),
    }
    defaults.update(overrides)
    return RuntimeRefs(**defaults)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestHeartbeatPluginSetup:
    """Tests for the heartbeat plugin setup() entry point."""

    def test_setup_registers_service(self) -> None:
        """setup() registers exactly one ServiceLike."""
        from nanobot.plugins.builtin.heartbeat import setup

        ctx = PluginContext("heartbeat", {"enabled": True, "interval_s": 60}, Path("/tmp"))
        setup(ctx)

        services = ctx._collect_services()
        assert len(services) == 1

    def test_setup_disabled_by_default(self) -> None:
        """With no config, the plugin registers a disabled service."""
        from nanobot.plugins.builtin.heartbeat import setup

        ctx = PluginContext("heartbeat", {}, Path("/tmp"))
        setup(ctx)

        services = ctx._collect_services()
        assert len(services) == 1
        assert not services[0].enabled


class TestHeartbeatPluginLifecycle:
    """Tests for the HeartbeatPlugin service lifecycle."""

    def test_set_runtime_creates_heartbeat_service(self) -> None:
        """set_runtime() creates an internal HeartbeatService when enabled."""
        from nanobot.plugins.builtin.heartbeat import HeartbeatPlugin

        plugin = HeartbeatPlugin(workspace=Path("/tmp"), enabled=True, interval_s=60)
        assert plugin._service is None

        refs = _make_refs()
        plugin.set_runtime(refs)
        assert plugin._service is not None

    def test_set_runtime_noop_when_disabled(self) -> None:
        """set_runtime() does nothing when plugin is disabled."""
        from nanobot.plugins.builtin.heartbeat import HeartbeatPlugin

        plugin = HeartbeatPlugin(workspace=Path("/tmp"), enabled=False)
        refs = _make_refs()
        plugin.set_runtime(refs)
        assert plugin._service is None

    @pytest.mark.asyncio
    async def test_start_stop_lifecycle(self) -> None:
        """start() and stop() propagate to the inner HeartbeatService."""
        from nanobot.plugins.builtin.heartbeat import HeartbeatPlugin

        plugin = HeartbeatPlugin(workspace=Path("/tmp"), enabled=True, interval_s=60)
        refs = _make_refs()
        plugin.set_runtime(refs)

        with patch.object(plugin._service, "start", new_callable=AsyncMock) as mock_start:
            await plugin.start()
            mock_start.assert_awaited_once()

        with patch.object(plugin._service, "stop") as mock_stop:
            plugin.stop()
            mock_stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_disabled_config_noop(self) -> None:
        """When disabled, start() is a no-op (no service created)."""
        from nanobot.plugins.builtin.heartbeat import HeartbeatPlugin

        plugin = HeartbeatPlugin(workspace=Path("/tmp"), enabled=False)
        await plugin.start()  # Should not raise
        plugin.stop()  # Should not raise
