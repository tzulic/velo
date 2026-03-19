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
