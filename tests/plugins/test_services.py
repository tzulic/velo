"""Tests for plugin services, runtime refs, and channels."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.plugins.manager import PluginManager
from nanobot.plugins.types import (
    PluginContext,
    RuntimeRefs,
    ServiceLike,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class FakeService:
    """Minimal ServiceLike implementation."""

    def __init__(self) -> None:
        self.started = False
        self.stopped = False

    async def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True


class RuntimeAwareService:
    """ServiceLike + RuntimeAware."""

    def __init__(self) -> None:
        self.started = False
        self.stopped = False
        self.runtime: RuntimeRefs | None = None

    def set_runtime(self, refs: RuntimeRefs) -> None:
        self.runtime = refs

    async def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True


class FailingService:
    """Service whose start() raises."""

    async def start(self) -> None:
        raise RuntimeError("boom")

    def stop(self) -> None:
        pass


def _make_refs(**overrides: Any) -> RuntimeRefs:
    """Create a RuntimeRefs with sensible defaults."""
    defaults = {
        "provider": MagicMock(),
        "model": "test-model",
        "bus": MagicMock(),
    }
    defaults.update(overrides)
    return RuntimeRefs(**defaults)


# ---------------------------------------------------------------------------
# PluginContext tests
# ---------------------------------------------------------------------------

class TestPluginContextServices:
    """Tests for register_service / register_channel on PluginContext."""

    def test_register_service_collected(self) -> None:
        """Services appear in _collect_services after registration."""
        ctx = PluginContext("test", {}, Path("/tmp"))
        svc = FakeService()
        ctx.register_service(svc)
        assert svc in ctx._collect_services()

    def test_register_channel_collected(self) -> None:
        """Channels appear in _collect_channels after registration."""
        ctx = PluginContext("test", {}, Path("/tmp"))
        ch = MagicMock()
        ctx.register_channel(ch)
        assert ch in ctx._collect_channels()

    def test_empty_by_default(self) -> None:
        """No services or channels by default."""
        ctx = PluginContext("test", {}, Path("/tmp"))
        assert ctx._collect_services() == []
        assert ctx._collect_channels() == []


# ---------------------------------------------------------------------------
# PluginManager tests
# ---------------------------------------------------------------------------

class TestPluginManagerRuntime:
    """Tests for set_runtime, start/stop services."""

    @pytest.mark.asyncio
    async def test_set_runtime_propagates_to_runtime_aware(self) -> None:
        """RuntimeAware services receive the refs."""
        mgr = PluginManager(Path("/tmp"), {})
        svc = RuntimeAwareService()
        mgr._services.append(svc)

        refs = _make_refs()
        mgr.set_runtime(refs)
        assert svc.runtime is refs

    @pytest.mark.asyncio
    async def test_set_runtime_skips_non_runtime_aware(self) -> None:
        """Services without set_runtime are not affected."""
        mgr = PluginManager(Path("/tmp"), {})
        svc = FakeService()
        mgr._services.append(svc)

        refs = _make_refs()
        mgr.set_runtime(refs)  # Should not raise
        assert not hasattr(svc, "runtime")

    @pytest.mark.asyncio
    async def test_start_services_calls_start(self) -> None:
        """All services are started."""
        mgr = PluginManager(Path("/tmp"), {})
        svc1 = FakeService()
        svc2 = FakeService()
        mgr._services.extend([svc1, svc2])

        await mgr.start_services()
        assert svc1.started
        assert svc2.started

    @pytest.mark.asyncio
    async def test_stop_services_calls_stop_reversed(self) -> None:
        """Services are stopped in reverse registration order."""
        mgr = PluginManager(Path("/tmp"), {})
        stop_order: list[str] = []

        class TrackedService:
            def __init__(self, name: str) -> None:
                self.name = name

            async def start(self) -> None:
                pass

            def stop(self) -> None:
                stop_order.append(self.name)

        mgr._services.extend([TrackedService("a"), TrackedService("b"), TrackedService("c")])
        await mgr.stop_services()
        assert stop_order == ["c", "b", "a"]

    @pytest.mark.asyncio
    async def test_service_start_failure_isolated(self) -> None:
        """One failing start doesn't block others."""
        mgr = PluginManager(Path("/tmp"), {})
        good = FakeService()
        mgr._services.extend([FailingService(), good])

        await mgr.start_services()
        assert good.started

    @pytest.mark.asyncio
    async def test_shutdown_stops_services_before_hooks(self) -> None:
        """shutdown() calls stop_services before on_shutdown hooks."""
        mgr = PluginManager(Path("/tmp"), {})
        svc = FakeService()
        mgr._services.append(svc)

        call_order: list[str] = []

        async def on_shutdown_hook() -> None:
            call_order.append(f"hook:svc_stopped={svc.stopped}")

        from nanobot.plugins.types import HookEntry
        mgr._hooks["on_shutdown"].append(HookEntry(callback=on_shutdown_hook))
        mgr._services.append(svc)  # Added twice intentionally for the stop tracking

        await mgr.shutdown()
        # The hook should see that the service was already stopped
        assert any("svc_stopped=True" in s for s in call_order)

    @pytest.mark.asyncio
    async def test_get_plugin_channels_returns_registered(self) -> None:
        """Channels are accessible via get_plugin_channels."""
        mgr = PluginManager(Path("/tmp"), {})
        ch = MagicMock()
        mgr._channels.append(ch)
        assert ch in mgr.get_plugin_channels()

    @pytest.mark.asyncio
    async def test_backwards_compatible_v1_plugin(self) -> None:
        """A v1 plugin (tools + hooks only, no services) still works."""
        mgr = PluginManager(Path("/tmp"), {})
        # Simulate a v1 load — no services, no channels
        assert mgr._services == []
        assert mgr._channels == []

        refs = _make_refs()
        mgr.set_runtime(refs)  # Should not raise
        await mgr.start_services()  # No-op
        await mgr.stop_services()  # No-op
        assert mgr.get_plugin_channels() == []
