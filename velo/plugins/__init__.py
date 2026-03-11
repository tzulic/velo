"""Plugin system for nanobot."""

from velo.plugins.manager import PluginManager
from velo.plugins.types import PluginContext, RuntimeRefs, ServiceLike

__all__ = ["PluginContext", "PluginManager", "RuntimeRefs", "ServiceLike"]
