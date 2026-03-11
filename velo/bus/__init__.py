"""Message bus module for decoupled channel-agent communication."""

from velo.bus.events import InboundMessage, OutboundMessage
from velo.bus.queue import MessageBus

__all__ = ["MessageBus", "InboundMessage", "OutboundMessage"]
