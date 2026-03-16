"""Heartbeat builtin plugin — wraps HeartbeatService as a plugin service.

This plugin is auto-discovered but disabled by default. Enable it via
``config.plugins.heartbeat.enabled = true`` with an optional ``interval_s``.

When active, the manual heartbeat code in the gateway skips itself
(``"heartbeat" in plugin_mgr.plugin_names``).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from velo.heartbeat.service import HeartbeatService
    from velo.plugins.types import PluginContext, RuntimeRefs


class HeartbeatPlugin:
    """Plugin service wrapping the existing HeartbeatService.

    Implements ``ServiceLike`` and ``RuntimeAware`` protocols.
    """

    def __init__(self, workspace: Path, interval_s: int = 1800, enabled: bool = False) -> None:
        self.workspace = workspace
        self.interval_s = interval_s
        self.enabled = enabled
        self._service: HeartbeatService | None = None

    def set_runtime(self, refs: RuntimeRefs) -> None:
        """Create the HeartbeatService with runtime-provided dependencies.

        Args:
            refs: Late-bound runtime references.
        """
        if not self.enabled:
            return

        from velo.heartbeat.service import HeartbeatService

        async def on_execute(tasks: str) -> str:
            """Execute heartbeat tasks through the agent loop."""
            if refs.process_direct is None:
                logger.warning("heartbeat_plugin: process_direct not available")
                return ""
            return await refs.process_direct(
                tasks,
                session_key="heartbeat",
                channel="cli",
                chat_id="direct",
            )

        async def on_notify(response: str) -> None:
            """Deliver heartbeat response via the message bus."""
            if refs.publish_outbound is None:
                return
            from velo.bus.events import OutboundMessage

            await refs.publish_outbound(
                OutboundMessage(
                    channel="cli",
                    chat_id="direct",
                    content=response,
                )
            )

        self._service = HeartbeatService(
            workspace=self.workspace,
            provider=refs.provider,
            model=refs.model,
            on_execute=on_execute,
            on_notify=on_notify,
            interval_s=self.interval_s,
            enabled=self.enabled,
            session_manager=refs.session_manager,
        )

    async def start(self) -> None:
        """Start the heartbeat service."""
        if self._service:
            await self._service.start()

    def stop(self) -> None:
        """Stop the heartbeat service."""
        if self._service:
            self._service.stop()


# Module-level state shared between register() and activate()
_plugin_instance: HeartbeatPlugin | None = None


def register(ctx: PluginContext) -> None:
    """Plugin entry point — prepare the heartbeat plugin.

    Args:
        ctx: Plugin context with config and workspace.
    """
    enabled = ctx.config.get("enabled", False)
    interval_s = ctx.config.get("interval_s", 1800)

    plugin = HeartbeatPlugin(
        workspace=ctx.workspace,
        interval_s=interval_s,
        enabled=enabled,
    )

    global _plugin_instance
    _plugin_instance = plugin

    logger.debug(
        "heartbeat_plugin.register: enabled={}, interval_s={}",
        enabled,
        interval_s,
    )


async def activate(ctx: PluginContext) -> None:
    """Activate the heartbeat background service.

    Args:
        ctx: Plugin context with config and workspace.
    """
    if _plugin_instance is not None:
        ctx.register_service(_plugin_instance)
