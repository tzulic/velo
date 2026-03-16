# Plugin Engine v2 Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade Velo's plugin engine from 6 hooks + single-phase lifecycle to 18 hooks + manifests + two-phase lifecycle + HTTP routes + config validation.

**Architecture:** Replace `velo/plugins/types.py` and `velo/plugins/manager.py` with expanded hook system (3 dispatch strategies), add `manifest.py` (plugin.json loading), `validation.py` (config schema checking), and `http.py` (route registration + aiohttp server). Migrate all 16 existing plugins from `setup()` to `register()`/`activate()`.

**Tech Stack:** Python 3.11+, asyncio, aiohttp (existing dep), pytest + pytest-asyncio

**Spec:** `docs/superpowers/specs/2026-03-16-plugin-engine-v2-design.md`

---

## Chunk 1: Core Types & Hook System

### Task 1: Expand hook definitions and types in `types.py`

**Files:**
- Modify: `velo/plugins/types.py`
- Test: `tests/plugins/test_hooks.py`

- [ ] **Step 1: Write failing tests for new hook types and HOOKS dict**

Create `tests/plugins/test_hooks.py`:

```python
"""Tests for expanded hook system."""

import pytest

from velo.plugins.types import HOOKS, HookType


class TestHookDefinitions:
    """Verify all 18 hooks are defined with correct strategies."""

    def test_hook_count(self):
        assert len(HOOKS) == 18

    def test_fire_and_forget_hooks(self):
        expected = {
            "on_startup", "on_shutdown", "message_received", "message_sent",
            "agent_end", "before_reset", "session_start", "session_end",
            "subagent_spawned", "subagent_ended",
        }
        actual = {name for name, typ in HOOKS.items() if typ == "fire_and_forget"}
        assert actual == expected

    def test_modifying_hooks(self):
        expected = {
            "before_model_resolve", "before_prompt_build", "after_prompt_build",
            "before_tool_call", "after_tool_call", "message_sending",
            "before_message_write",
        }
        actual = {name for name, typ in HOOKS.items() if typ == "modifying"}
        assert actual == expected

    def test_claiming_hooks(self):
        expected = {"inbound_claim"}
        actual = {name for name, typ in HOOKS.items() if typ == "claiming"}
        assert actual == expected

    def test_before_response_removed(self):
        assert "before_response" not in HOOKS

    def test_hook_type_literal(self):
        valid_types = {"fire_and_forget", "modifying", "claiming"}
        for name, typ in HOOKS.items():
            assert typ in valid_types, f"Hook '{name}' has invalid type '{typ}'"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/plugins/test_hooks.py -v`
Expected: FAIL — `before_response` still exists, only 6 hooks defined, no `claiming` type

- [ ] **Step 3: Update `velo/plugins/types.py` with expanded hooks**

Replace the `HookType` and `HOOKS` definitions:

```python
HookType = Literal["fire_and_forget", "modifying", "claiming"]

HOOKS: dict[str, HookType] = {
    # Agent lifecycle
    "before_model_resolve": "modifying",
    "before_prompt_build": "modifying",
    "after_prompt_build": "modifying",
    "agent_end": "fire_and_forget",
    "before_reset": "fire_and_forget",
    # Message flow
    "message_received": "fire_and_forget",
    "inbound_claim": "claiming",
    "message_sending": "modifying",
    "message_sent": "fire_and_forget",
    # Tool execution
    "before_tool_call": "modifying",
    "after_tool_call": "modifying",
    "before_message_write": "modifying",
    # Session
    "session_start": "fire_and_forget",
    "session_end": "fire_and_forget",
    "subagent_spawned": "fire_and_forget",
    "subagent_ended": "fire_and_forget",
    # Gateway
    "on_startup": "fire_and_forget",
    "on_shutdown": "fire_and_forget",
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/plugins/test_hooks.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add velo/plugins/types.py tests/plugins/test_hooks.py
git commit -m "feat(plugins): expand hook definitions from 6 to 18 with claiming strategy"
```

---

### Task 2: Add `ctx.disable()`, `register_http_route()`, and HTTP types to `PluginContext`

**Files:**
- Modify: `velo/plugins/types.py`
- Test: `tests/plugins/test_hooks.py` (extend)

- [ ] **Step 1: Write failing tests for new PluginContext methods**

Append to `tests/plugins/test_hooks.py`:

```python
from pathlib import Path
from velo.plugins.types import PluginContext, HttpRequest, HttpResponse


class TestPluginContextDisable:
    """Test ctx.disable() graceful shutdown."""

    def test_disable_sets_flag(self):
        ctx = PluginContext(plugin_name="test", config={}, workspace=Path("/tmp"))
        assert not ctx._disabled
        ctx.disable("missing api_key")
        assert ctx._disabled
        assert ctx._disable_reason == "missing api_key"

    def test_not_disabled_by_default(self):
        ctx = PluginContext(plugin_name="test", config={}, workspace=Path("/tmp"))
        assert not ctx._disabled
        assert ctx._disable_reason == ""


class TestPluginContextHttpRoutes:
    """Test register_http_route()."""

    def test_register_route(self):
        ctx = PluginContext(plugin_name="test", config={}, workspace=Path("/tmp"))

        async def handler(req: HttpRequest) -> HttpResponse:
            return HttpResponse(status=200, body="ok")

        ctx.register_http_route(method="POST", path="/webhooks/test", handler=handler)
        routes = ctx._collect_http_routes()
        assert len(routes) == 1
        assert routes[0]["method"] == "POST"
        assert routes[0]["path"] == "/webhooks/test"

    def test_collect_empty_routes(self):
        ctx = PluginContext(plugin_name="test", config={}, workspace=Path("/tmp"))
        assert ctx._collect_http_routes() == []


class TestHttpTypes:
    """Test HttpRequest and HttpResponse dataclasses."""

    def test_http_request_fields(self):
        req = HttpRequest(method="POST", path="/test", body=b"hello", headers={}, query_params={})
        assert req.method == "POST"
        assert req.body == b"hello"

    def test_http_response_defaults(self):
        resp = HttpResponse()
        assert resp.status == 200
        assert resp.body == ""
        assert resp.headers == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/plugins/test_hooks.py::TestPluginContextDisable -v`
Expected: FAIL — `_disabled` attribute doesn't exist

- [ ] **Step 3: Add `disable()`, `register_http_route()`, HTTP types to `types.py`**

Add `HttpRequest` and `HttpResponse` dataclasses after `HookEntry`:

```python
@dataclass
class HttpRequest:
    """Incoming HTTP request for plugin route handlers."""

    method: str
    path: str
    body: bytes
    headers: dict[str, str]
    query_params: dict[str, str]


@dataclass
class HttpResponse:
    """Response from a plugin route handler."""

    status: int = 200
    body: str | bytes = ""
    headers: dict[str, str] = field(default_factory=dict)
```

Add to `PluginContext.__init__`:
```python
self._http_routes: list[dict[str, Any]] = []
self._disabled: bool = False
self._disable_reason: str = ""
```

Add methods to `PluginContext`:
```python
def disable(self, reason: str) -> None:
    """Gracefully disable this plugin during registration.

    Args:
        reason: Human-readable explanation logged and available to Volos agent.
    """
    self._disabled = True
    self._disable_reason = reason

def register_http_route(
    self,
    method: str,
    path: str,
    handler: Callable[..., Awaitable[Any]],
    metadata: dict[str, Any] | None = None,
) -> None:
    """Register an HTTP route on the gateway.

    Args:
        method: HTTP method (GET, POST, etc.).
        path: URL path (will be prefixed with /plugins/).
        handler: Async function(HttpRequest) -> HttpResponse.
        metadata: Optional metadata dict.
    """
    self._http_routes.append({
        "method": method.upper(),
        "path": path,
        "handler": handler,
        "metadata": metadata or {},
        "plugin_name": self.plugin_name,
    })

def _collect_http_routes(self) -> list[dict[str, Any]]:
    """Return all registered HTTP routes."""
    return list(self._http_routes)
```

Also add `field` to imports: `from dataclasses import dataclass, field`

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/plugins/test_hooks.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add velo/plugins/types.py tests/plugins/test_hooks.py
git commit -m "feat(plugins): add ctx.disable(), register_http_route(), HttpRequest/HttpResponse"
```

---

### Task 3: Add `claim()` method and update `pipe()` in `PluginManager`

**Files:**
- Modify: `velo/plugins/manager.py`
- Test: `tests/plugins/test_hooks.py` (extend)

- [ ] **Step 1: Write failing tests for `claim()` and updated `pipe()`**

Append to `tests/plugins/test_hooks.py`:

```python
import asyncio
from unittest.mock import AsyncMock
from velo.plugins.manager import PluginManager


class TestClaimDispatch:
    """Test claiming hook dispatch."""

    def _make_manager(self) -> PluginManager:
        mgr = PluginManager(workspace=Path("/tmp"), config={})
        mgr._loaded = True
        return mgr

    @pytest.mark.asyncio
    async def test_claim_returns_first_truthy(self):
        mgr = self._make_manager()
        mgr._hooks["inbound_claim"] = [
            HookEntry(callback=AsyncMock(return_value=None), priority=100),
            HookEntry(callback=AsyncMock(return_value={"handled": True}), priority=200),
            HookEntry(callback=AsyncMock(return_value={"handled": True}), priority=300),
        ]
        result = await mgr.claim("inbound_claim", content="hi", channel="telegram", chat_id="123")
        assert result == {"handled": True}
        # Third callback should NOT have been called
        mgr._hooks["inbound_claim"][2].callback.assert_not_called()

    @pytest.mark.asyncio
    async def test_claim_returns_none_when_no_claim(self):
        mgr = self._make_manager()
        mgr._hooks["inbound_claim"] = [
            HookEntry(callback=AsyncMock(return_value=None), priority=100),
        ]
        result = await mgr.claim("inbound_claim", content="hi", channel="telegram", chat_id="123")
        assert result is None

    @pytest.mark.asyncio
    async def test_claim_error_isolation(self):
        mgr = self._make_manager()
        mgr._hooks["inbound_claim"] = [
            HookEntry(callback=AsyncMock(side_effect=RuntimeError("boom")), priority=100),
            HookEntry(callback=AsyncMock(return_value={"handled": True}), priority=200),
        ]
        result = await mgr.claim("inbound_claim", content="hi", channel="telegram", chat_id="123")
        assert result == {"handled": True}


class TestPipeCancelBlock:
    """Test pipe() cancel/block short-circuit."""

    def _make_manager(self) -> PluginManager:
        mgr = PluginManager(workspace=Path("/tmp"), config={})
        mgr._loaded = True
        return mgr

    @pytest.mark.asyncio
    async def test_pipe_cancel_short_circuits(self):
        mgr = self._make_manager()
        second_cb = AsyncMock(return_value="should not run")
        mgr._hooks["message_sending"] = [
            HookEntry(callback=AsyncMock(return_value={"cancel": True}), priority=100),
            HookEntry(callback=second_cb, priority=200),
        ]
        result = await mgr.pipe("message_sending", value="hello", channel="telegram", chat_id="123")
        assert result == {"cancel": True}
        second_cb.assert_not_called()

    @pytest.mark.asyncio
    async def test_pipe_block_short_circuits(self):
        mgr = self._make_manager()
        mgr._hooks["before_tool_call"] = [
            HookEntry(callback=AsyncMock(return_value={"__block": True}), priority=100),
        ]
        result = await mgr.pipe("before_tool_call", value={"cmd": "rm -rf /"}, tool_name="exec")
        assert result == {"__block": True}

    @pytest.mark.asyncio
    async def test_pipe_passthrough_unchanged(self):
        mgr = self._make_manager()
        mgr._hooks["after_prompt_build"] = [
            HookEntry(callback=AsyncMock(return_value=None), priority=100),
        ]
        result = await mgr.pipe("after_prompt_build", value="original prompt")
        assert result == "original prompt"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/plugins/test_hooks.py::TestClaimDispatch -v`
Expected: FAIL — `claim()` method doesn't exist

- [ ] **Step 3: Add `claim()` and update `pipe()` in `manager.py`**

Add `claim()` method after `pipe()`:

```python
async def claim(self, hook: str, **kwargs: Any) -> Any:
    """First-claim-wins hook dispatch.

    Callbacks run sequentially by priority. The first to return a truthy
    result wins; remaining callbacks are skipped.

    Args:
        hook: Hook name (must be a claiming hook).
        **kwargs: Arguments passed to each callback.

    Returns:
        The first truthy result, or None if no callback claimed.
    """
    entries = self._hooks.get(hook, [])
    for entry in entries:
        try:
            result = await self._call(entry.callback, **kwargs)
            if result:
                return result
        except Exception:
            logger.exception("plugin.claim_failed: {}", hook)
    return None
```

Update `pipe()` to short-circuit on cancel/block — replace the inner try block:

```python
try:
    result = await self._call(entry.callback, value=value, **kwargs)
    if result is not None:
        # Short-circuit on cancel or block
        if isinstance(result, dict) and (result.get("cancel") or result.get("__block")):
            return result
        value = result
except Exception:
    logger.exception("plugin.pipe_failed: {} (skipping callback)", hook)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/plugins/test_hooks.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add velo/plugins/manager.py tests/plugins/test_hooks.py
git commit -m "feat(plugins): add claim() dispatch and cancel/block short-circuit in pipe()"
```

---

## Chunk 2: Manifest System & Config Validation

### Task 4: Create `manifest.py` — plugin.json loading

**Files:**
- Create: `velo/plugins/manifest.py`
- Test: `tests/plugins/test_manifest.py`

- [ ] **Step 1: Write failing tests for manifest loading**

Create `tests/plugins/test_manifest.py`:

```python
"""Tests for plugin manifest loading."""

import json
import pytest
from pathlib import Path

from velo.plugins.manifest import load_manifest, validate_manifest, PluginManifest


@pytest.fixture
def tmp_plugin(tmp_path):
    """Create a minimal plugin directory with plugin.json."""
    plugin_dir = tmp_path / "test-plugin"
    plugin_dir.mkdir()
    (plugin_dir / "__init__.py").write_text("def register(ctx): pass\n")
    return plugin_dir


def _write_manifest(plugin_dir: Path, data: dict) -> Path:
    path = plugin_dir / "plugin.json"
    path.write_text(json.dumps(data))
    return path


class TestLoadManifest:
    def test_load_valid_manifest(self, tmp_plugin):
        _write_manifest(tmp_plugin, {
            "id": "test-plugin",
            "name": "Test Plugin",
            "version": "1.0.0",
            "description": "A test plugin",
            "category": "horizontal",
            "tags": ["test"],
            "config_schema": {},
            "requires": {"channels": [], "env": [], "plugins": []},
            "hooks": [],
            "tools": [],
            "services": False,
            "context_provider": False,
            "used_by_templates": [],
            "ui_hints": {},
        })
        manifest = load_manifest(tmp_plugin)
        assert manifest is not None
        assert manifest.id == "test-plugin"
        assert manifest.version == "1.0.0"

    def test_load_missing_manifest_returns_none(self, tmp_plugin):
        result = load_manifest(tmp_plugin)
        assert result is None

    def test_load_invalid_json_returns_none(self, tmp_plugin):
        (tmp_plugin / "plugin.json").write_text("not json{{{")
        result = load_manifest(tmp_plugin)
        assert result is None

    def test_load_minimal_manifest_with_defaults(self, tmp_plugin):
        _write_manifest(tmp_plugin, {
            "id": "minimal",
            "name": "Minimal",
            "version": "0.1.0",
            "description": "Minimal plugin",
        })
        manifest = load_manifest(tmp_plugin)
        assert manifest is not None
        assert manifest.category == ""
        assert manifest.tags == []
        assert manifest.config_schema == {}


class TestValidateManifest:
    def test_valid_manifest(self):
        m = PluginManifest(
            id="test", name="Test", version="1.0.0", description="desc",
            category="horizontal", tags=[], config_schema={},
            requires={"channels": [], "env": [], "plugins": []},
            hooks=[], tools=[], services=False, context_provider=False,
            used_by_templates=[], ui_hints={},
        )
        errors = validate_manifest(m)
        assert errors == []

    def test_missing_id(self):
        m = PluginManifest(
            id="", name="Test", version="1.0.0", description="desc",
            category="horizontal", tags=[], config_schema={},
            requires={}, hooks=[], tools=[], services=False,
            context_provider=False, used_by_templates=[], ui_hints={},
        )
        errors = validate_manifest(m)
        assert any("id" in e for e in errors)

    def test_missing_version(self):
        m = PluginManifest(
            id="test", name="Test", version="", description="desc",
            category="horizontal", tags=[], config_schema={},
            requires={}, hooks=[], tools=[], services=False,
            context_provider=False, used_by_templates=[], ui_hints={},
        )
        errors = validate_manifest(m)
        assert any("version" in e for e in errors)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/plugins/test_manifest.py -v`
Expected: FAIL — module `velo.plugins.manifest` does not exist

- [ ] **Step 3: Implement `velo/plugins/manifest.py`**

```python
"""Plugin manifest loading and validation.

Reads plugin.json files and parses them into PluginManifest dataclasses.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from loguru import logger


@dataclass
class PluginManifest:
    """Parsed plugin.json manifest."""

    id: str
    name: str
    version: str
    description: str
    category: str = ""
    tags: list[str] = field(default_factory=list)
    config_schema: dict[str, Any] = field(default_factory=dict)
    requires: dict[str, list[str]] = field(default_factory=dict)
    hooks: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    services: bool = False
    context_provider: bool = False
    used_by_templates: list[str] = field(default_factory=list)
    ui_hints: dict[str, str] = field(default_factory=dict)


def load_manifest(plugin_dir: Path) -> PluginManifest | None:
    """Load and parse plugin.json from a plugin directory.

    Args:
        plugin_dir: Path to the plugin directory containing plugin.json.

    Returns:
        PluginManifest if found and valid JSON, None otherwise.
    """
    manifest_path = plugin_dir / "plugin.json"
    if not manifest_path.is_file():
        return None

    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("plugin.manifest_invalid: {} ({})", plugin_dir.name, exc)
        return None

    if not isinstance(raw, dict):
        logger.warning("plugin.manifest_not_dict: {}", plugin_dir.name)
        return None

    return PluginManifest(
        id=raw.get("id", ""),
        name=raw.get("name", ""),
        version=raw.get("version", ""),
        description=raw.get("description", ""),
        category=raw.get("category", ""),
        tags=raw.get("tags", []),
        config_schema=raw.get("config_schema", {}),
        requires=raw.get("requires", {}),
        hooks=raw.get("hooks", []),
        tools=raw.get("tools", []),
        services=raw.get("services", False),
        context_provider=raw.get("context_provider", False),
        used_by_templates=raw.get("used_by_templates", []),
        ui_hints=raw.get("ui_hints", {}),
    )


def validate_manifest(manifest: PluginManifest) -> list[str]:
    """Validate a parsed manifest for required fields.

    Args:
        manifest: The parsed manifest to validate.

    Returns:
        List of error strings. Empty list means valid.
    """
    errors: list[str] = []
    if not manifest.id:
        errors.append("manifest missing required field 'id'")
    if not manifest.version:
        errors.append("manifest missing required field 'version'")
    if not manifest.name:
        errors.append("manifest missing required field 'name'")
    if not manifest.description:
        errors.append("manifest missing required field 'description'")
    return errors
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/plugins/test_manifest.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add velo/plugins/manifest.py tests/plugins/test_manifest.py
git commit -m "feat(plugins): add manifest.py for plugin.json loading and validation"
```

---

### Task 5: Create `validation.py` — config schema validation

**Files:**
- Create: `velo/plugins/validation.py`
- Test: `tests/plugins/test_validation.py`

- [ ] **Step 1: Write failing tests for config validation**

Create `tests/plugins/test_validation.py`:

```python
"""Tests for plugin config schema validation."""

import pytest

from velo.plugins.validation import validate_config


class TestValidateConfig:
    def test_empty_schema_accepts_anything(self):
        config, errors = validate_config({"foo": "bar"}, {}, "test")
        assert errors == []
        assert config == {"foo": "bar"}

    def test_required_field_present(self):
        schema = {"api_key": {"type": "string", "required": True}}
        config, errors = validate_config({"api_key": "abc"}, schema, "test")
        assert errors == []

    def test_required_field_missing(self):
        schema = {"api_key": {"type": "string", "required": True}}
        config, errors = validate_config({}, schema, "test")
        assert len(errors) == 1
        assert "api_key" in errors[0]

    def test_default_applied(self):
        schema = {"port": {"type": "integer", "default": 8080}}
        config, errors = validate_config({}, schema, "test")
        assert errors == []
        assert config["port"] == 8080

    def test_default_not_applied_when_present(self):
        schema = {"port": {"type": "integer", "default": 8080}}
        config, errors = validate_config({"port": 9090}, schema, "test")
        assert config["port"] == 9090

    def test_wrong_type_string(self):
        schema = {"count": {"type": "integer"}}
        config, errors = validate_config({"count": "not a number"}, schema, "test")
        assert len(errors) == 1
        assert "integer" in errors[0]

    def test_wrong_type_boolean(self):
        schema = {"enabled": {"type": "boolean"}}
        config, errors = validate_config({"enabled": "yes"}, schema, "test")
        assert len(errors) == 1

    def test_enum_valid(self):
        schema = {"mode": {"type": "string", "enum": ["fast", "slow"]}}
        config, errors = validate_config({"mode": "fast"}, schema, "test")
        assert errors == []

    def test_enum_invalid(self):
        schema = {"mode": {"type": "string", "enum": ["fast", "slow"]}}
        config, errors = validate_config({"mode": "medium"}, schema, "test")
        assert len(errors) == 1
        assert "fast" in errors[0]

    def test_unknown_fields_ignored(self):
        schema = {"known": {"type": "string"}}
        config, errors = validate_config({"known": "yes", "extra": 42}, schema, "test")
        assert errors == []
        assert config["extra"] == 42

    def test_no_config_no_required_fields(self):
        schema = {"opt": {"type": "string", "default": "hello"}}
        config, errors = validate_config({}, schema, "test")
        assert errors == []
        assert config["opt"] == "hello"

    def test_no_config_with_required_fields(self):
        schema = {"key": {"type": "string", "required": True}}
        config, errors = validate_config({}, schema, "test")
        assert len(errors) == 1

    def test_array_type(self):
        schema = {"tags": {"type": "array", "default": []}}
        config, errors = validate_config({"tags": ["a", "b"]}, schema, "test")
        assert errors == []

    def test_array_type_wrong(self):
        schema = {"tags": {"type": "array"}}
        config, errors = validate_config({"tags": "not-a-list"}, schema, "test")
        assert len(errors) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/plugins/test_validation.py -v`
Expected: FAIL — module doesn't exist

- [ ] **Step 3: Implement `velo/plugins/validation.py`**

```python
"""Config schema validation for plugins.

Validates plugin config dicts against the config_schema from plugin.json.
No external dependencies — simple type + required + default + enum checks.
"""

from __future__ import annotations

from typing import Any

_TYPE_MAP: dict[str, type | tuple[type, ...]] = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "array": list,
    "object": dict,
}


def validate_config(
    config: dict[str, Any],
    schema: dict[str, Any],
    plugin_name: str,
) -> tuple[dict[str, Any], list[str]]:
    """Validate plugin config against manifest schema.

    Args:
        config: Raw config dict from config.json plugins section.
        schema: config_schema dict from plugin.json manifest.
        plugin_name: For error messages.

    Returns:
        Tuple of (validated config with defaults applied, list of error strings).
        Empty error list means valid.
    """
    errors: list[str] = []
    result = dict(config)

    for field_name, field_schema in schema.items():
        if not isinstance(field_schema, dict):
            continue

        required = field_schema.get("required", False)
        default = field_schema.get("default")
        field_type = field_schema.get("type", "")
        enum_values = field_schema.get("enum")

        # Apply default if missing
        if field_name not in result:
            if required:
                errors.append(f"{plugin_name}: missing required config '{field_name}'")
                continue
            if default is not None:
                result[field_name] = default
            continue

        value = result[field_name]

        # Type check
        expected_type = _TYPE_MAP.get(field_type)
        if expected_type and not isinstance(value, expected_type):
            errors.append(
                f"{plugin_name}: '{field_name}' must be {field_type}, "
                f"got {type(value).__name__}"
            )
            continue

        # Enum check
        if enum_values and value not in enum_values:
            errors.append(
                f"{plugin_name}: '{field_name}' must be one of "
                f"{enum_values}, got '{value}'"
            )

    return result, errors
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/plugins/test_validation.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add velo/plugins/validation.py tests/plugins/test_validation.py
git commit -m "feat(plugins): add config schema validation against plugin.json"
```

---

## Chunk 3: Two-Phase Lifecycle & Manager Rewrite

### Task 6: Rewrite `PluginManager` for two-phase lifecycle + manifest discovery

**Files:**
- Modify: `velo/plugins/manager.py`
- Test: `tests/plugins/test_lifecycle.py`

- [ ] **Step 1: Write failing tests for two-phase loading**

Create `tests/plugins/test_lifecycle.py`:

```python
"""Tests for two-phase plugin lifecycle."""

import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock

from velo.plugins.manager import PluginManager


@pytest.fixture
def plugin_env(tmp_path):
    """Create workspace with plugin dirs."""
    workspace = tmp_path / "workspace"
    plugins_dir = workspace / "plugins"
    plugins_dir.mkdir(parents=True)
    return workspace, plugins_dir


def _create_plugin(plugins_dir: Path, name: str, *, needs_activate: bool = False, manifest: dict | None = None):
    """Create a minimal plugin with manifest."""
    plugin_dir = plugins_dir / name
    plugin_dir.mkdir()

    # Write plugin.json
    m = manifest or {
        "id": name, "name": name, "version": "1.0.0",
        "description": f"Test {name}", "config_schema": {},
    }
    (plugin_dir / "plugin.json").write_text(json.dumps(m))

    # Write __init__.py
    if needs_activate:
        code = (
            "from velo.plugins.types import PluginContext\n"
            "def register(ctx: PluginContext) -> None:\n"
            "    ctx._test_registered = True\n"
            "async def activate(ctx: PluginContext) -> None:\n"
            "    ctx._test_activated = True\n"
        )
    else:
        code = (
            "from velo.plugins.types import PluginContext\n"
            "def register(ctx: PluginContext) -> None:\n"
            "    ctx._test_registered = True\n"
        )
    (plugin_dir / "__init__.py").write_text(code)


class TestTwoPhaseLifecycle:
    @pytest.mark.asyncio
    async def test_register_only_plugin(self, plugin_env):
        workspace, plugins_dir = plugin_env
        _create_plugin(plugins_dir, "simple")
        mgr = PluginManager(workspace=workspace, config={})
        await mgr.load_all()
        assert "simple" in mgr.plugin_names

    @pytest.mark.asyncio
    async def test_plugin_without_manifest_fails(self, plugin_env):
        workspace, plugins_dir = plugin_env
        plugin_dir = plugins_dir / "no-manifest"
        plugin_dir.mkdir()
        (plugin_dir / "__init__.py").write_text("def register(ctx): pass\n")
        # No plugin.json
        mgr = PluginManager(workspace=workspace, config={})
        await mgr.load_all()
        assert "no-manifest" not in mgr.plugin_names

    @pytest.mark.asyncio
    async def test_plugin_without_register_fails(self, plugin_env):
        workspace, plugins_dir = plugin_env
        plugin_dir = plugins_dir / "old-style"
        plugin_dir.mkdir()
        (plugin_dir / "plugin.json").write_text(json.dumps({
            "id": "old-style", "name": "Old", "version": "1.0.0", "description": "test",
        }))
        (plugin_dir / "__init__.py").write_text("def setup(ctx): pass\n")
        mgr = PluginManager(workspace=workspace, config={})
        await mgr.load_all()
        assert "old-style" not in mgr.plugin_names

    @pytest.mark.asyncio
    async def test_disabled_via_config(self, plugin_env):
        workspace, plugins_dir = plugin_env
        _create_plugin(plugins_dir, "disabled-one")
        mgr = PluginManager(
            workspace=workspace,
            config={"disabled-one": {"enabled": False}},
        )
        await mgr.load_all()
        assert "disabled-one" not in mgr.plugin_names

    @pytest.mark.asyncio
    async def test_config_validation_disables_plugin(self, plugin_env):
        workspace, plugins_dir = plugin_env
        _create_plugin(plugins_dir, "needs-key", manifest={
            "id": "needs-key", "name": "Needs Key", "version": "1.0.0",
            "description": "test",
            "config_schema": {
                "api_key": {"type": "string", "required": True},
            },
        })
        mgr = PluginManager(workspace=workspace, config={})
        await mgr.load_all()
        assert "needs-key" not in mgr.plugin_names
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/plugins/test_lifecycle.py -v`
Expected: FAIL — current manager has no manifest support

- [ ] **Step 3: Rewrite `velo/plugins/manager.py`**

Full rewrite of `PluginManager` to support: manifest-first discovery, config validation, two-phase lifecycle (register → activate), all three dispatch strategies.

Key changes from current `manager.py`:
- `discover()`: Now requires `plugin.json`. Reads manifest, skips plugins without one.
- `_load_plugin()` → split into `_register_plugin()` and `_activate_plugin()`
- `_register_plugin()`: Validates config against schema, calls `register(ctx)`, collects registrations
- `_activate_plugin()`: Calls `activate(ctx)` if it exists
- `load_all()`: Phase 0 discover → Phase 1 register → Phase 2 activate → Phase 3 start services + fire on_startup
- Import `load_manifest` from `manifest.py` and `validate_config` from `validation.py`
- `PluginMeta` gets `manifest` field (imported from manifest module)

The full implementation is ~400 lines. The key structural change:

```python
async def load_all(self) -> None:
    if self._loaded:
        return
    self._loaded = True

    metas = self.discover()

    # Phase 1: Register
    for meta in metas:
        try:
            self._register_plugin(meta)
        except Exception:
            logger.exception("plugin.register_failed: {}", meta.name)
            meta.enabled = False

    # Sort hooks by priority
    for hook_name in self._hooks:
        self._hooks[hook_name].sort(key=lambda e: e.priority)

    # Phase 2: Activate
    for meta in [m for m in metas if m.enabled]:
        try:
            await self._activate_plugin(meta)
        except Exception:
            logger.exception("plugin.activate_failed: {}", meta.name)

    # Phase 3: Services + startup hooks
    await self.start_services()
    await self.fire("on_startup")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/plugins/test_lifecycle.py tests/plugins/test_hooks.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add velo/plugins/manager.py tests/plugins/test_lifecycle.py
git commit -m "feat(plugins): rewrite manager for two-phase lifecycle + manifest discovery"
```

---

## Chunk 4: HTTP Server & Route System

### Task 7: Create `http.py` — RouteTable + PluginHttpServer

**Files:**
- Create: `velo/plugins/http.py`
- Test: `tests/plugins/test_http.py`

- [ ] **Step 1: Write failing tests for RouteTable**

Create `tests/plugins/test_http.py`:

```python
"""Tests for plugin HTTP route system."""

import pytest

from velo.plugins.http import RouteTable
from velo.plugins.types import HttpRequest, HttpResponse


class TestRouteTable:
    def test_register_route(self):
        rt = RouteTable()
        async def handler(req): return HttpResponse(status=200)
        rt.register("POST", "/webhooks/stripe", handler, plugin_name="test")
        assert rt.has_routes()

    def test_collision_detection(self):
        rt = RouteTable()
        async def handler(req): return HttpResponse(status=200)
        rt.register("POST", "/webhooks/stripe", handler, plugin_name="a")
        with pytest.raises(ValueError, match="already registered"):
            rt.register("POST", "/webhooks/stripe", handler, plugin_name="b")

    def test_different_methods_no_collision(self):
        rt = RouteTable()
        async def handler(req): return HttpResponse(status=200)
        rt.register("POST", "/webhooks/stripe", handler, plugin_name="a")
        rt.register("GET", "/webhooks/stripe", handler, plugin_name="a")
        assert rt.has_routes()

    @pytest.mark.asyncio
    async def test_dispatch(self):
        rt = RouteTable()
        async def handler(req: HttpRequest) -> HttpResponse:
            return HttpResponse(status=200, body=f"got {req.path}")
        rt.register("POST", "/webhooks/test", handler, plugin_name="test")
        req = HttpRequest(method="POST", path="/plugins/webhooks/test", body=b"", headers={}, query_params={})
        resp = await rt.dispatch(req)
        assert resp.status == 200
        assert "got" in str(resp.body)

    @pytest.mark.asyncio
    async def test_dispatch_not_found(self):
        rt = RouteTable()
        req = HttpRequest(method="GET", path="/plugins/unknown", body=b"", headers={}, query_params={})
        resp = await rt.dispatch(req)
        assert resp.status == 404

    def test_empty_table(self):
        rt = RouteTable()
        assert not rt.has_routes()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/plugins/test_http.py -v`
Expected: FAIL — module doesn't exist

- [ ] **Step 3: Implement `velo/plugins/http.py`**

```python
"""Plugin HTTP route system.

RouteTable collects plugin-registered routes. PluginHttpServer serves them
on the gateway port using aiohttp.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiohttp import web
from loguru import logger

from velo.plugins.types import HttpRequest, HttpResponse

RouteHandler = Callable[[HttpRequest], Awaitable[HttpResponse]]

_PLUGIN_PREFIX = "/plugins"


class RouteTable:
    """Stores plugin HTTP routes and dispatches requests."""

    def __init__(self) -> None:
        self._routes: dict[tuple[str, str], tuple[RouteHandler, str]] = {}

    def register(
        self,
        method: str,
        path: str,
        handler: RouteHandler,
        plugin_name: str,
    ) -> None:
        """Register a route. Raises ValueError on collision.

        Args:
            method: HTTP method (POST, GET, etc.).
            path: URL path (without /plugins/ prefix).
            handler: Async handler function.
            plugin_name: Owning plugin name for error messages.
        """
        key = (method.upper(), path)
        if key in self._routes:
            existing_plugin = self._routes[key][1]
            raise ValueError(
                f"Route {method} {path} already registered by "
                f"plugin '{existing_plugin}'"
            )
        self._routes[key] = (handler, plugin_name)

    def has_routes(self) -> bool:
        """Return True if any routes are registered."""
        return len(self._routes) > 0

    async def dispatch(self, request: HttpRequest) -> HttpResponse:
        """Dispatch a request to the matching handler.

        Args:
            request: The incoming HTTP request.

        Returns:
            HttpResponse from the handler, or 404 if no match.
        """
        # Strip /plugins prefix for lookup
        path = request.path
        if path.startswith(_PLUGIN_PREFIX):
            path = path[len(_PLUGIN_PREFIX):]

        key = (request.method.upper(), path)
        entry = self._routes.get(key)
        if entry is None:
            return HttpResponse(status=404, body="Not found")

        handler, plugin_name = entry
        try:
            return await handler(request)
        except Exception:
            logger.exception("plugin.http_handler_failed: {} {}", request.method, path)
            return HttpResponse(status=500, body="Internal server error")


class PluginHttpServer:
    """Lightweight aiohttp server for plugin routes.

    Args:
        route_table: The route table with registered handlers.
        host: Bind host. Default "0.0.0.0".
        port: Bind port. Default 18790.
    """

    def __init__(self, route_table: RouteTable, host: str = "0.0.0.0", port: int = 18790) -> None:
        self._route_table = route_table
        self._host = host
        self._port = port
        self._runner: web.AppRunner | None = None

    async def start(self) -> None:
        """Start the HTTP server."""
        app = web.Application()
        app.router.add_route("*", "/plugins/{path:.*}", self._handle)
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self._host, self._port)
        await site.start()
        logger.info("plugin.http_server_started: {}:{}", self._host, self._port)

    async def stop(self) -> None:
        """Stop the HTTP server."""
        if self._runner:
            await self._runner.cleanup()
            logger.info("plugin.http_server_stopped")

    async def _handle(self, request: web.Request) -> web.Response:
        """aiohttp handler that bridges to RouteTable."""
        body = await request.read()
        plugin_req = HttpRequest(
            method=request.method,
            path=request.path,
            body=body,
            headers=dict(request.headers),
            query_params=dict(request.query),
        )
        plugin_resp = await self._route_table.dispatch(plugin_req)
        return web.Response(
            status=plugin_resp.status,
            body=plugin_resp.body,
            headers=plugin_resp.headers,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/plugins/test_http.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add velo/plugins/http.py tests/plugins/test_http.py
git commit -m "feat(plugins): add HTTP route table and plugin HTTP server"
```

---

### Task 8: Update `__init__.py` exports

**Files:**
- Modify: `velo/plugins/__init__.py`

- [ ] **Step 1: Update exports**

```python
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
```

- [ ] **Step 2: Commit**

```bash
git add velo/plugins/__init__.py
git commit -m "feat(plugins): update __init__.py exports for v2 modules"
```

---

## Chunk 5: Hook Integration Points

### Task 9: Fire new hooks from `loop.py`, `context.py`, `session/manager.py`, `subagent.py`, `delivery_queue.py`

This is the wiring task — connecting the 12 new hooks to their fire sites in the codebase. Each hook gets a single `await self.plugin_manager.fire(...)` or `await self.plugin_manager.pipe(...)` or `await self.plugin_manager.claim(...)` call at the right location.

**Files:**
- Modify: `velo/agent/loop.py` — `message_received`, `inbound_claim`, `message_sending`, `agent_end`, `before_reset`, `before_model_resolve`
- Modify: `velo/agent/context.py` — `before_prompt_build`
- Modify: `velo/session/manager.py` — `session_start`, `session_end`, `before_message_write`
- Modify: `velo/agent/subagent.py` — `subagent_spawned`, `subagent_ended`
- Modify: `velo/bus/delivery_queue.py` — `message_sent`

Each hook is a single line insertion. The exact line numbers depend on the current code, but the pattern is consistent:

**For fire_and_forget hooks** (non-blocking, fire in background):
```python
await self.plugin_manager.fire("hook_name", kwarg1=val1, kwarg2=val2)
```

**For modifying hooks** (transform value, may cancel):
```python
result = await self.plugin_manager.pipe("hook_name", value=val, kwarg1=val1)
if isinstance(result, dict) and result.get("cancel"):
    return  # Skip sending
```

**For claiming hooks** (first-claim-wins):
```python
claim = await self.plugin_manager.claim("inbound_claim", content=msg.content, channel=msg.channel, chat_id=msg.chat_id)
if claim and claim.get("handled"):
    return  # Message claimed by plugin, don't process
```

- [ ] **Step 1: Add hooks to `loop.py`**

Read the file, find the exact insertion points for each hook, and add the fire/pipe/claim calls. Also rename `before_response` pipe call to `message_sending` and add cancel check.

- [ ] **Step 2: Add `before_prompt_build` to `context.py`**

Before prompt assembly, pipe through `before_prompt_build` with initial value `{"prepend_context": "", "append_context": ""}`. Merge result into prompt.

- [ ] **Step 3: Add `session_start`, `session_end`, `before_message_write` to `session/manager.py`**

Add session tracking (seen session keys set) and idle-timeout detection. Fire `session_start` on first message per session key. Fire `before_message_write` before JSONL append. Add idle timeout timer for `session_end`.

- [ ] **Step 4: Add `subagent_spawned`, `subagent_ended` to `subagent.py`**

Fire after spawn and after child completion.

- [ ] **Step 5: Add `message_sent` to `delivery_queue.py`**

Fire after successful delivery in `DeliveryQueue.send()`.

- [ ] **Step 6: Run full test suite**

Run: `uv run pytest -v`
Expected: All existing tests pass (new hooks are no-ops when no plugins register for them)

- [ ] **Step 7: Commit**

```bash
git add velo/agent/loop.py velo/agent/context.py velo/session/manager.py velo/agent/subagent.py velo/bus/delivery_queue.py
git commit -m "feat(plugins): wire 12 new hooks into agent loop, session manager, delivery queue"
```

---

## Chunk 6: Plugin Migration + Manifests

### Task 10: Create `plugin.json` manifests for all 16 plugins

**Files:**
- Create: 16 `plugin.json` files across `library/plugins/` and `velo/plugins/builtin/`

- [ ] **Step 1: Create manifests for all 8 horizontal plugins**

One `plugin.json` per plugin in `library/plugins/horizontal/{name}/plugin.json`. Each manifest mirrors the existing config keys from the plugin's `__init__.py` docstring and the `plugin-catalog.md`.

- [ ] **Step 2: Create manifests for all 6 vertical plugins**

One `plugin.json` per plugin in `library/plugins/vertical/{vertical}/{name}/plugin.json`.

- [ ] **Step 3: Create manifests for 2 builtin plugins**

`velo/plugins/builtin/heartbeat/plugin.json` and `velo/plugins/builtin/composio/plugin.json`.

- [ ] **Step 4: Commit**

```bash
git add library/plugins/**/plugin.json velo/plugins/builtin/*/plugin.json
git commit -m "feat(plugins): add plugin.json manifests for all 16 plugins"
```

---

### Task 11: Migrate all 16 plugins from `setup()` to `register()`/`activate()`

**Files:**
- Modify: All 14 `library/plugins/**/__init__.py`
- Modify: `velo/plugins/builtin/heartbeat/__init__.py`
- Modify: `velo/plugins/builtin/composio/__init__.py`

Each migration follows the same pattern:

**For register-only plugins** (9 plugins):
```python
# Before:
def setup(ctx: PluginContext) -> None:
    ctx.register_tool(MyTool())
    ctx.on("before_response", my_hook)

# After:
def register(ctx: PluginContext) -> None:
    ctx.register_tool(MyTool())
    ctx.on("message_sending", my_hook)  # renamed hook
```

**For plugins needing activate** (7 plugins):
```python
# Before:
def setup(ctx: PluginContext) -> None:
    ctx.register_tool(MyTool())
    ctx.register_service(MyService())
    ctx.on("on_startup", startup_fn)

# After:
def register(ctx: PluginContext) -> None:
    ctx.register_tool(MyTool())
    ctx.on("on_startup", startup_fn)

async def activate(ctx: PluginContext) -> None:
    ctx.register_service(MyService())
```

Also rename all `before_response` hooks to `message_sending` in every plugin that uses it.

- [ ] **Step 1: Migrate 9 register-only plugins**

escalation-manager, business-hours, conversation-analytics, rate-limiter, auto-translate, lead-scorer, ticket-tracker, csat-survey

- [ ] **Step 2: Migrate 7 activate plugins**

scheduled-digest, knowledge-base, webhook-receiver, health-checker, sla-monitor, heartbeat, composio

- [ ] **Step 3: Run full test suite**

Run: `uv run pytest -v`
Expected: All pass

- [ ] **Step 4: Commit**

```bash
git add library/plugins/ velo/plugins/builtin/
git commit -m "feat(plugins): migrate all 16 plugins to register()/activate() lifecycle"
```

---

## Chunk 7: Gateway Integration & Final Verification

### Task 12: Start PluginHttpServer in gateway command

**Files:**
- Modify: `velo/cli/commands.py`

- [ ] **Step 1: Add HTTP server startup to gateway command**

After `plugin_mgr.load_all()`, check if the route table has routes. If yes, start `PluginHttpServer` on the gateway port.

```python
# After plugin loading in gateway() command:
from velo.plugins.http import PluginHttpServer

http_server = None
if plugin_mgr.route_table.has_routes():
    http_server = PluginHttpServer(plugin_mgr.route_table, port=port)
    await http_server.start()
```

Add cleanup in shutdown:
```python
if http_server:
    await http_server.stop()
```

This requires `PluginManager` to expose a `route_table` property.

- [ ] **Step 2: Commit**

```bash
git add velo/cli/commands.py
git commit -m "feat(plugins): start plugin HTTP server in gateway when routes registered"
```

---

### Task 13: Full integration test + final verification

**Files:**
- Create: `tests/plugins/test_integration.py`

- [ ] **Step 1: Write integration test**

```python
"""Integration test: full plugin lifecycle."""

import json
import pytest
from pathlib import Path

from velo.plugins.manager import PluginManager


@pytest.fixture
def full_env(tmp_path):
    workspace = tmp_path / "workspace"
    plugins_dir = workspace / "plugins"
    plugins_dir.mkdir(parents=True)

    # Create a plugin with tool, hook, service, context provider, http route
    plugin_dir = plugins_dir / "full-test"
    plugin_dir.mkdir()
    (plugin_dir / "plugin.json").write_text(json.dumps({
        "id": "full-test", "name": "Full Test", "version": "1.0.0",
        "description": "Integration test plugin",
        "config_schema": {
            "greeting": {"type": "string", "default": "hello"},
        },
    }))
    (plugin_dir / "__init__.py").write_text('''
from velo.plugins.types import PluginContext, HttpRequest, HttpResponse
from velo.agent.tools.base import Tool
from typing import Any


class GreetTool(Tool):
    name = "greet"
    description = "Say hello"

    async def execute(self, **kwargs: Any) -> str:
        return "hello"


def register(ctx: PluginContext) -> None:
    ctx.register_tool(GreetTool())
    ctx.on("message_sending", lambda value, **kw: value)
    ctx.add_context_provider(lambda: f"Greeting: {ctx.config.get('greeting', 'hi')}")

    async def handle_webhook(req: HttpRequest) -> HttpResponse:
        return HttpResponse(status=200, body="ok")

    ctx.register_http_route(method="POST", path="/webhooks/test", handler=handle_webhook)
''')
    return workspace


class TestFullLifecycle:
    @pytest.mark.asyncio
    async def test_discover_register_activate(self, full_env):
        mgr = PluginManager(workspace=full_env, config={})
        await mgr.load_all()

        assert "full-test" in mgr.plugin_names
        assert len(mgr.get_all_tools()) == 1
        assert mgr.route_table.has_routes()

        context = await mgr.get_context_additions()
        assert "Greeting: hello" in context
```

- [ ] **Step 2: Run all tests**

Run: `uv run pytest tests/plugins/ -v`
Expected: All PASS

- [ ] **Step 3: Run linter**

Run: `uv run ruff check velo/plugins/ tests/plugins/`
Run: `uv run ruff format velo/plugins/ tests/plugins/`

- [ ] **Step 4: Final commit**

```bash
git add tests/plugins/test_integration.py
git commit -m "test(plugins): add full lifecycle integration test"
```

---

## Notes for Executor

**Plugin count:** All 16 plugins exist. The library plugins are in `~/Volos/library/plugins/` (NOT inside the `velo/` repo). They are deployed to customer workspaces via SSH by the Volos agent. The 2 builtins are in `velo/plugins/builtin/`.

**Task 6 (Manager rewrite):** The plan provides the `load_all()` skeleton. The executor should read the current `manager.py` (363 lines) and refactor it in-place. Key changes:
- `discover()`: Require `plugin.json`. Use `load_manifest()` from `manifest.py`. Skip plugins without manifest. Add `manifest` field to `PluginMeta`.
- `_load_plugin()` → split into `_register_plugin()` (calls `register()`) and `_activate_plugin()` (calls `activate()` if it exists)
- `_register_plugin()`: Call `validate_config()` before `register()`. If validation fails, set `meta.enabled = False`.
- Add `_route_table: RouteTable` attribute. Expose via `route_table` property.
- Collect HTTP routes from `ctx._collect_http_routes()` into `_route_table` during registration.

**Task 9 (Hook wiring):** The executor should `grep` for existing hook fire sites in `loop.py` (search for `plugin_manager.fire` and `plugin_manager.pipe`) and follow the same pattern. Key insertion points:
- `loop.py:~706` — existing `before_tool_call` pipe. Rename kwarg if needed.
- `loop.py` — search for `before_response` and rename to `message_sending`, add cancel check.
- `loop.py` — search for where inbound messages arrive (the `process_message` or `_handle_message` method) for `message_received` and `inbound_claim`.
- `session/manager.py` — idle timeout: add a `_last_message_time: dict[str, float]` tracking dict. On each message write, update timestamp. Add a periodic check (every 60s) that fires `session_end` for sessions idle > 30 min.

**Task 10-11 (Manifests + migrations):** The executor should read each plugin's `__init__.py` and its entry in `plugin-catalog.md` to build the `plugin.json`. Use the escalation-manager manifest in the spec (Section 2.1) as the template. For migrations, each plugin's `setup()` function becomes `register()`, with service registration moved to `activate()` for the 7 plugins that need it.

**Library plugin discovery:** Library plugins are NOT discovered automatically by the manager. They are deployed by the Volos agent (via SSH) into the customer's `~/.velo/workspace/plugins/` directory. The manager only scans `builtin/` and `workspace/plugins/`. The manifests in `library/plugins/` are read by the Volos agent directly (via `ssh_read_file`) to understand what's available before deploying.

**Bool/int type check:** In `validation.py`, add `bool` exclusion for integer type check:
```python
if field_type == "integer" and isinstance(value, bool):
    errors.append(f"{plugin_name}: '{field_name}' must be integer, got boolean")
    continue
```

---

## Summary

| Chunk | Tasks | What It Delivers |
|-------|-------|-----------------|
| 1 | Tasks 1-3 | 18 hooks, 3 dispatch strategies, ctx.disable(), HTTP types |
| 2 | Tasks 4-5 | Manifest loading, config schema validation |
| 3 | Task 6 | Two-phase manager rewrite |
| 4 | Tasks 7-8 | HTTP server + route system, updated exports |
| 5 | Task 9 | Hook wiring into loop, session, subagent, delivery |
| 6 | Tasks 10-11 | 16 manifests + 16 plugin migrations |
| 7 | Tasks 12-13 | Gateway integration, full integration test |
