"""Dashboard channel implementation using Supabase Realtime Broadcast."""

import asyncio
import time
import uuid
from typing import Any

from loguru import logger
from realtime._async.channel import AsyncRealtimeChannel
from realtime._async.client import AsyncRealtimeClient
from realtime.types import BroadcastPayload, RealtimeSubscribeStates

from velo.bus.events import InboundMessage, OutboundMessage
from velo.bus.queue import MessageBus
from velo.channels.base import BaseChannel
from velo.config.schema import DashboardConfig

# Bound for safety-net set of own message IDs
_MAX_OWN_IDS = 200


class DashboardChannel(BaseChannel):
    """Dashboard channel using Supabase Realtime Broadcast.

    Supports single-agent chat and multi-agent room (Slack-like group chat).
    In multi-agent mode, agents see each other's messages and selectively respond.
    """

    name = "dashboard"

    def __init__(self, config: DashboardConfig, bus: MessageBus) -> None:
        super().__init__(config, bus)
        self.config: DashboardConfig = config
        self._client: AsyncRealtimeClient | None = None
        self._channel: AsyncRealtimeChannel | None = None
        self._agent_turn_count: int = 0
        self._last_agent_response: float = 0.0
        self._own_message_ids: set[str] = set()

    async def start(self) -> None:
        """Start the Supabase Realtime connection."""
        if not self.config.supabase_url or not self.config.supabase_key:
            logger.error("Dashboard supabase_url/supabase_key not configured")
            return
        if not self.config.room_id:
            logger.error("Dashboard room_id not configured")
            return

        self._running = True

        while self._running:
            try:
                ws_url = self._build_ws_url()
                logger.info("Connecting to dashboard Realtime: {}", ws_url)

                self._client = AsyncRealtimeClient(
                    ws_url,
                    token=self.config.supabase_key,
                    auto_reconnect=True,
                    hb_interval=25,
                    max_retries=10,
                )
                await self._client.connect()

                self._channel = self._client.channel(self.config.room_id)
                self._channel.on_broadcast("user_message", self._on_user_message)
                self._channel.on_broadcast("agent_message", self._on_agent_message)
                self._channel.on_broadcast("stop", self._on_stop)
                await self._channel.subscribe(self._on_subscribe)

                logger.info("Dashboard channel subscribed to room {}", self.config.room_id)

                while self._running:
                    await asyncio.sleep(1)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("Dashboard Realtime error: {}", e)
                if self._running:
                    logger.info("Reconnecting to Dashboard Realtime in 5 seconds...")
                    await asyncio.sleep(5)

    async def stop(self) -> None:
        """Stop the dashboard channel."""
        self._running = False
        if self._client:
            try:
                await self._client.close()
            except Exception as e:
                logger.warning("Dashboard client close failed: {}", e)
            self._client = None
        self._channel = None

    async def send(self, msg: OutboundMessage) -> None:
        """Send a message via Supabase Realtime Broadcast."""
        if not self._channel:
            logger.warning("Dashboard channel not connected")
            return

        # Silently drop [NO_RESPONSE] messages (multi-agent opt-out)
        if msg.content and msg.content.strip() == "[NO_RESPONSE]":
            return

        # Progress messages → typing event
        if msg.metadata.get("_progress"):
            await self._channel.send_broadcast(
                "typing",
                {
                    "agent_id": self.config.agent_id,
                    "agent_name": self.config.agent_name,
                },
            )
            return

        message_id = str(uuid.uuid4())
        self._own_message_ids.add(message_id)
        # Bound the safety-net set
        if len(self._own_message_ids) > _MAX_OWN_IDS:
            # Discard oldest by removing arbitrary elements
            while len(self._own_message_ids) > _MAX_OWN_IDS // 2:
                self._own_message_ids.pop()

        await self._channel.send_broadcast(
            "agent_message",
            {
                "message_id": message_id,
                "agent_id": self.config.agent_id,
                "agent_name": self.config.agent_name,
                "content": msg.content or "",
            },
        )

    # ── Broadcast callbacks (sync → async bridge) ─────────────────────

    def _on_user_message(self, payload: BroadcastPayload) -> None:
        """Sync callback for user_message broadcast events."""
        asyncio.get_event_loop().create_task(self._handle_user_message(dict(payload)))

    def _on_agent_message(self, payload: BroadcastPayload) -> None:
        """Sync callback for agent_message broadcast events."""
        asyncio.get_event_loop().create_task(self._handle_agent_message(dict(payload)))

    def _on_stop(self, payload: BroadcastPayload) -> None:
        """Sync callback for stop broadcast events."""
        asyncio.get_event_loop().create_task(self._handle_stop(dict(payload)))

    def _on_subscribe(self, state: RealtimeSubscribeStates, error: Exception | None) -> None:
        """Subscription state callback."""
        if state == RealtimeSubscribeStates.SUBSCRIBED:
            logger.info("Dashboard Realtime subscribed to room {}", self.config.room_id)
        elif error:
            logger.error("Dashboard Realtime subscribe error: {}", error)

    # ── Async message handlers ────────────────────────────────────────

    async def _handle_user_message(self, payload: dict[str, Any]) -> None:
        """Handle an incoming user message."""
        data = payload.get("payload", payload)
        sender_id = str(data.get("sender_id", ""))
        content = data.get("content", "")
        sender_name = data.get("sender_name", "User")

        if not content:
            return

        # User message resets agent turn counter
        self._agent_turn_count = 0

        # Multi-agent context injection
        if len(self.config.participants) > 1:
            participants_str = ", ".join(self.config.participants)
            content = (
                f"[Room participants: {participants_str}]\n"
                f"[From: {sender_name}]\n"
                f"Only respond if relevant to your expertise. "
                f"If @mentioned, always respond.\n"
                f"If you have nothing to add, reply with exactly: [NO_RESPONSE]\n\n"
                f"{content}"
            )

        await self._handle_message(
            sender_id=sender_id,
            chat_id=self.config.room_id,
            content=content,
            session_key=f"dashboard:{self.config.room_id}",
        )

    async def _handle_agent_message(self, payload: dict[str, Any]) -> None:
        """Handle an incoming agent message from another agent."""
        data = payload.get("payload", payload)
        agent_id = str(data.get("agent_id", ""))
        message_id = data.get("message_id", "")

        # Skip own messages (safety net)
        if agent_id == self.config.agent_id:
            return
        if message_id in self._own_message_ids:
            return

        content = data.get("content", "")
        agent_name = data.get("agent_name", "Agent")

        if not content:
            return

        # Enforce agent turn limit
        self._agent_turn_count += 1
        if self._agent_turn_count > self.config.max_agent_turns:
            logger.warning(
                "Dashboard agent turn limit reached ({}/{}), ignoring agent message",
                self._agent_turn_count,
                self.config.max_agent_turns,
            )
            return

        # Apply cooldown between agent-to-agent responses
        now = time.monotonic()
        elapsed = now - self._last_agent_response
        wait = self.config.agent_cooldown_s - elapsed
        if wait > 0:
            await asyncio.sleep(wait)

        # Format agent message with context
        if len(self.config.participants) > 1:
            participants_str = ", ".join(self.config.participants)
            formatted_content = (
                f"[Room participants: {participants_str}]\n"
                f"[From: {agent_name} (agent)]\n"
                f"Only respond if relevant to your expertise. "
                f"If @mentioned, always respond.\n"
                f"If you have nothing to add, reply with exactly: [NO_RESPONSE]\n\n"
                f"[{agent_name}]: {content}"
            )
        else:
            formatted_content = f"[{agent_name}]: {content}"

        await self._handle_message(
            sender_id=agent_id,
            chat_id=self.config.room_id,
            content=formatted_content,
            session_key=f"dashboard:{self.config.room_id}",
        )

        self._last_agent_response = time.monotonic()

    async def _handle_stop(self, _payload: dict[str, Any]) -> None:
        """Handle a stop broadcast event."""
        msg = InboundMessage(
            channel="dashboard",
            sender_id="system",
            chat_id=self.config.room_id,
            content="/stop",
            session_key_override=f"dashboard:{self.config.room_id}",
        )
        await self.bus.publish_inbound(msg)

    # ── Helpers ───────────────────────────────────────────────────────

    def _build_ws_url(self) -> str:
        """Build the Supabase Realtime WebSocket URL.

        Supports two modes:
        - Proxy mode: URL starts with ws:// or wss:// (direct WebSocket endpoint)
        - Standard mode: Derive WS URL from Supabase project URL
        """
        url = self.config.supabase_url.rstrip("/")
        # Proxy mode: URL is already a WebSocket endpoint
        if url.startswith("ws://") or url.startswith("wss://"):
            return url
        # Standard Supabase: derive WS URL from project URL
        host = url.split("//", 1)[-1]  # "xyz.supabase.co"
        project_ref = host.split(".")[0]  # "xyz"
        return f"wss://{project_ref}.supabase.co/realtime/v1/websocket"
