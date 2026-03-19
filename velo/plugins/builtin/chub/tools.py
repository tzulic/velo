"""Context Hub tools: chub_search, chub_get, chub_annotate."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

from loguru import logger

from velo.agent.tools.base import Tool


async def _run_chub(
    args: list[str],
    timeout: int,
    env_override: dict[str, str] | None = None,
) -> tuple[str, str, int]:
    """Run a chub CLI command via subprocess.

    Args:
        args: Command arguments (e.g. ["search", "stripe"]).
        timeout: Timeout in seconds.
        env_override: Extra env vars to merge into the subprocess environment.

    Returns:
        Tuple of (stdout, stderr, returncode).

    Raises:
        FileNotFoundError: If chub CLI is not installed.
        asyncio.TimeoutError: If the command exceeds timeout.
    """
    env = {**os.environ}
    if env_override:
        env.update(env_override)

    proc = await asyncio.create_subprocess_exec(
        "chub",
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise
    return stdout.decode("utf-8", errors="replace"), stderr.decode("utf-8", errors="replace"), proc.returncode or 0


def _read_global_annotation(global_path: str, doc_id: str) -> str:
    """Read a global annotation file for a given doc_id.

    Args:
        global_path: Directory containing global annotation JSON files.
        doc_id: Doc identifier (e.g. "stripe/api").

    Returns:
        Annotation note text, or "" if not found.
    """
    safe_name = doc_id.replace("/", "-") + ".json"
    path = Path(global_path) / safe_name
    if not path.is_file():
        return ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("note", "")
    except (json.JSONDecodeError, OSError):
        logger.debug("chub.global_annotation_read_failed: doc_id={}", doc_id)
        return ""


class ChubSearchTool(Tool):
    """Search Context Hub for available API documentation."""

    name = "chub_search"
    description = (
        "Search Context Hub for curated API documentation. "
        "Returns a list of available docs with IDs and descriptions. "
        "Use chub_get to fetch a specific doc by ID."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query (e.g. 'stripe payments', 'openai chat')",
            },
        },
        "required": ["query"],
    }

    def __init__(self, workspace: Path, config: dict[str, Any]) -> None:
        """Initialize search tool.

        Args:
            workspace: Agent workspace path.
            config: Plugin config dict.
        """
        self._workspace = workspace
        self._timeout = config.get("search_timeout", 10)

    async def execute(self, **kwargs: Any) -> str:
        """Execute chub search.

        Args:
            **kwargs: Must include 'query' (str).

        Returns:
            Search results or error message.
        """
        query = kwargs.get("query", "")
        try:
            stdout, stderr, rc = await _run_chub(["search", query], self._timeout)
            if rc != 0:
                return f"Search failed: {stderr.strip() or stdout.strip()}"
            return stdout.strip() or "No results found."
        except FileNotFoundError:
            return "Context Hub CLI (chub) not available. Cannot search docs."
        except asyncio.TimeoutError:
            return "Context Hub search timed out."
        except Exception:
            logger.exception("chub_search.execute_failed")
            return "Error searching Context Hub."


class ChubGetTool(Tool):
    """Fetch API documentation from Context Hub."""

    name = "chub_get"
    description = (
        "Fetch curated API documentation by ID from Context Hub. "
        "Use chub_search first to find available doc IDs."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "doc_id": {
                "type": "string",
                "description": "Doc ID to fetch (e.g. 'stripe/api', 'openai/chat-api')",
            },
            "lang": {
                "type": "string",
                "description": "Language variant (py, js, ts). Optional — auto-inferred if only one exists.",
            },
        },
        "required": ["doc_id"],
    }

    def __init__(self, workspace: Path, config: dict[str, Any]) -> None:
        """Initialize get tool.

        Args:
            workspace: Agent workspace path.
            config: Plugin config dict.
        """
        self._workspace = workspace
        self._timeout = config.get("get_timeout", 15)
        self._lang_default = config.get("lang_default", "py")
        self._global_path = config.get(
            "global_annotations_path", "/opt/volos/shared/chub-annotations"
        )

    async def execute(self, **kwargs: Any) -> str:
        """Execute chub get with workspace-scoped annotations.

        Args:
            **kwargs: Must include 'doc_id' (str), optional 'lang' (str).

        Returns:
            Doc content with annotations, or error message.
        """
        doc_id = kwargs.get("doc_id", "")
        lang = kwargs.get("lang") or self._lang_default

        args = ["get", doc_id, "--lang", lang]
        # Reason: override HOME so chub reads annotations from
        # {workspace}/.chub/annotations/ instead of ~/.chub/annotations/
        env_override = {"HOME": str(self._workspace)}

        try:
            stdout, stderr, rc = await _run_chub(args, self._timeout, env_override)
            if rc != 0:
                err = stderr.strip() or stdout.strip()
                if "not found" in err.lower():
                    return f"Doc '{doc_id}' not found. Try chub_search to find available docs."
                return f"Fetch failed: {err}"

            output = stdout.strip()

            # Append global annotation if no workspace annotation present
            has_workspace_annotation = "[Agent note" in output
            if not has_workspace_annotation:
                global_note = _read_global_annotation(self._global_path, doc_id)
                if global_note:
                    output += f"\n\n---\n[Global note]\n{global_note}"

            return output or f"Doc '{doc_id}' returned empty content."

        except FileNotFoundError:
            return "Context Hub CLI (chub) not available. Cannot fetch docs."
        except asyncio.TimeoutError:
            return "Context Hub fetch timed out."
        except Exception:
            logger.exception("chub_get.execute_failed")
            return "Error fetching doc from Context Hub."


class ChubAnnotateTool(Tool):
    """Annotate a Context Hub doc with a local note."""

    name = "chub_annotate"
    description = (
        "Save a note on a Context Hub doc for future sessions. "
        "Use this when you discover a quirk, workaround, or environment-specific "
        "detail that isn't in the official doc. The note appears on future chub_get calls."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "doc_id": {
                "type": "string",
                "description": "Doc ID to annotate (e.g. 'stripe/api')",
            },
            "note": {
                "type": "string",
                "description": "Note to attach (e.g. 'Webhook verification needs raw body')",
            },
        },
        "required": ["doc_id", "note"],
    }

    def __init__(self, workspace: Path, config: dict[str, Any]) -> None:
        """Initialize annotate tool.

        Args:
            workspace: Agent workspace path.
            config: Plugin config dict.
        """
        self._workspace = workspace
        self._timeout = config.get("annotate_timeout", 5)

    async def execute(self, **kwargs: Any) -> str:
        """Execute chub annotate with workspace-scoped storage.

        Args:
            **kwargs: Must include 'doc_id' (str) and 'note' (str).

        Returns:
            Confirmation message or error.
        """
        doc_id = kwargs.get("doc_id", "")
        note = kwargs.get("note", "")

        # Reason: override HOME so annotation writes to
        # {workspace}/.chub/annotations/ (per-agent isolation)
        env_override = {"HOME": str(self._workspace)}

        try:
            stdout, stderr, rc = await _run_chub(
                ["annotate", doc_id, note], self._timeout, env_override
            )
            if rc != 0:
                return f"Annotation failed: {stderr.strip() or stdout.strip()}"
            return f"Annotated '{doc_id}' — note will appear on future fetches."

        except FileNotFoundError:
            return "Context Hub CLI (chub) not available. Cannot annotate."
        except asyncio.TimeoutError:
            return "Context Hub annotate timed out."
        except Exception:
            logger.exception("chub_annotate.execute_failed")
            return "Error annotating doc."
