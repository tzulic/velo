"""Plugin system for Velo."""

from velo.plugins.http import PluginHttpServer, RouteTable
from velo.plugins.manager import PluginManager
from velo.plugins.manifest import PluginManifest, load_manifest, validate_manifest
from velo.plugins.types import (
    HttpRequest,
    HttpResponse,
    PluginContext,
    RuntimeRefs,
    ServiceLike,
)
from velo.plugins.validation import validate_config

__all__ = [
    "HttpRequest",
    "HttpResponse",
    "PluginContext",
    "PluginHttpServer",
    "PluginManager",
    "PluginManifest",
    "RouteTable",
    "RuntimeRefs",
    "ServiceLike",
    "load_manifest",
    "validate_config",
    "validate_manifest",
]
