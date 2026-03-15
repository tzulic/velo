"""Skill management tool for agent self-improvement.

Allows the agent to create, edit, patch, delete, list, and read workspace
skills. New/edited skills are security-scanned and validated before writing.
"""

from __future__ import annotations

import json
import re
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

from loguru import logger

from velo.agent.security import scan_content
from velo.agent.skills import SkillsLoader
from velo.agent.tools.base import Tool

# Builtin skills directory (cannot be deleted by the agent)
_BUILTIN_SKILLS_DIR = Path(__file__).parent.parent.parent / "skills"

# Validation constants
_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_NAME_MAX_LEN = 64


def _validate_name(name: str | None) -> str | None:
    """Validate a skill name.

    Args:
        name: Skill name to validate.

    Returns:
        Error message if invalid, None if valid.
    """
    if not name:
        return "Skill name is required."
    if len(name) > _NAME_MAX_LEN:
        return f"Skill name must be at most {_NAME_MAX_LEN} characters."
    if not _NAME_PATTERN.match(name):
        return "Skill name must be lowercase alphanumeric with hyphens (e.g. 'my-skill')."
    return None


def _validate_frontmatter(content: str) -> str | None:
    """Validate that SKILL.md content has required frontmatter.

    Args:
        content: Full SKILL.md content to validate.

    Returns:
        Error message if invalid, None if valid.
    """
    if not content.startswith("---"):
        return "SKILL.md must start with YAML frontmatter (---). Include name: and description:."
    # Find closing ---
    end = content.find("---", 3)
    if end == -1:
        return "SKILL.md frontmatter is not closed (missing second ---)."
    frontmatter = content[3:end]
    if "name:" not in frontmatter:
        return "SKILL.md frontmatter must include 'name:'."
    if "description:" not in frontmatter:
        return "SKILL.md frontmatter must include 'description:'."
    return None


def _validate_skill_content(name: str | None, content: str) -> str | None:
    """Validate name + content for create/edit actions.

    Args:
        name: Skill name.
        content: Full SKILL.md content.

    Returns:
        Error message if invalid, None if valid.
    """
    if err := _validate_name(name):
        return err
    if not content:
        return "Content is required."
    if err := _validate_frontmatter(content):
        return err
    if threat := scan_content(content):
        return f"Content blocked by security scan: {threat}"
    return None


def _is_builtin_skill(name: str) -> bool:
    """Check if a skill is a builtin (cannot be deleted).

    Args:
        name: Skill name to check.

    Returns:
        True if the skill exists in the builtin skills directory.
    """
    return (_BUILTIN_SKILLS_DIR / name / "SKILL.md").exists()


class SkillManageTool(Tool):
    """Manage workspace skills: create, edit, patch, delete, list, or read.

    Used for agent self-improvement — saving reusable procedures after
    completing complex tasks.
    """

    name = "skill_manage"
    description = (
        "Manage workspace skills: create, edit, patch, delete, list, or read. "
        "Use after completing complex tasks to save reusable procedures."
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["create", "edit", "patch", "delete", "list", "read"],
                "description": "Action to perform on skills.",
            },
            "name": {
                "type": "string",
                "description": "Skill name (lowercase, hyphens, max 64 chars). Required for all actions except list.",
            },
            "content": {
                "type": "string",
                "description": "Full SKILL.md content including frontmatter. Required for create and edit.",
            },
            "old_text": {
                "type": "string",
                "description": "Text to find in existing skill (patch only).",
            },
            "new_text": {
                "type": "string",
                "description": "Replacement text (patch only).",
            },
        },
        "required": ["action"],
    }

    def __init__(
        self,
        workspace: Path,
        invalidate_callback: Callable[[], None] | None = None,
    ) -> None:
        """Initialize skill management tool.

        Args:
            workspace: Path to the Velo workspace.
            invalidate_callback: Optional callback to invalidate prompt cache after changes.
        """
        self._workspace = workspace
        self._skills_dir = workspace / "skills"
        self._loader = SkillsLoader(workspace)
        self._invalidate = invalidate_callback

    async def execute(self, action: str, **kwargs: Any) -> str:
        """Execute a skill management action.

        Args:
            action: One of create, edit, patch, delete, list, read.
            **kwargs: Action-specific parameters.

        Returns:
            Result message or error.
        """
        handlers = {
            "create": self._create,
            "edit": self._edit,
            "patch": self._patch,
            "delete": self._delete,
            "list": self._list,
            "read": self._read,
        }
        handler = handlers.get(action)
        if not handler:
            return json.dumps(
                {"error": f"Unknown action: {action}. Use one of: {', '.join(handlers)}"}
            )

        try:
            return await handler(**kwargs)
        except Exception:
            logger.exception("skill_manage.{}_failed", action)
            return json.dumps({"error": f"skill_manage.{action} failed unexpectedly."})

    async def _create(self, name: str = "", content: str = "", **kwargs: Any) -> str:
        """Create a new workspace skill.

        Args:
            name: Skill name.
            content: Full SKILL.md content.
            **kwargs: Ignored.

        Returns:
            Success or error message.
        """
        if err := _validate_skill_content(name, content):
            return json.dumps({"error": err})

        skill_dir = self._skills_dir / name
        if (skill_dir / "SKILL.md").exists():
            return json.dumps({"error": f"Skill '{name}' already exists. Use 'edit' to update."})

        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")

        if self._invalidate:
            self._invalidate()

        logger.info("skill_manage.create_completed: name={}", name)
        return f"Skill '{name}' created successfully at {skill_dir / 'SKILL.md'}"

    async def _edit(self, name: str = "", content: str = "", **kwargs: Any) -> str:
        """Overwrite an existing skill with new content.

        Args:
            name: Skill name.
            content: Full new SKILL.md content.
            **kwargs: Ignored.

        Returns:
            Success or error message.
        """
        if err := _validate_skill_content(name, content):
            return json.dumps({"error": err})

        skill_file = self._skills_dir / name / "SKILL.md"
        if not skill_file.exists():
            return json.dumps({"error": f"Skill '{name}' not found. Use 'create' first."})

        skill_file.write_text(content, encoding="utf-8")

        if self._invalidate:
            self._invalidate()

        logger.info("skill_manage.edit_completed: name={}", name)
        return f"Skill '{name}' updated successfully."

    async def _patch(
        self, name: str = "", old_text: str = "", new_text: str = "", **kwargs: Any
    ) -> str:
        """Find and replace text in an existing skill.

        Args:
            name: Skill name.
            old_text: Text to find.
            new_text: Replacement text.
            **kwargs: Ignored.

        Returns:
            Success or error message.
        """
        if err := _validate_name(name):
            return json.dumps({"error": err})
        if not old_text:
            return json.dumps({"error": "old_text is required for patch action."})

        skill_file = self._skills_dir / name / "SKILL.md"
        if not skill_file.exists():
            return json.dumps({"error": f"Skill '{name}' not found."})

        current = skill_file.read_text(encoding="utf-8")
        if old_text not in current:
            return json.dumps({"error": f"old_text not found in skill '{name}'."})

        updated = current.replace(old_text, new_text, 1)

        if err := _validate_frontmatter(updated):
            return json.dumps({"error": f"Patch would break frontmatter: {err}"})
        if threat := scan_content(updated):
            return json.dumps({"error": f"Patched content blocked by security scan: {threat}"})

        skill_file.write_text(updated, encoding="utf-8")

        if self._invalidate:
            self._invalidate()

        logger.info("skill_manage.patch_completed: name={}", name)
        return f"Skill '{name}' patched successfully."

    async def _delete(self, name: str = "", **kwargs: Any) -> str:
        """Delete a workspace skill.

        Refuses to delete builtin skills.

        Args:
            name: Skill name to delete.
            **kwargs: Ignored.

        Returns:
            Success or error message.
        """
        if err := _validate_name(name):
            return json.dumps({"error": err})

        if _is_builtin_skill(name):
            return json.dumps({"error": f"Cannot delete builtin skill '{name}'."})

        skill_dir = self._skills_dir / name
        if not skill_dir.exists():
            return json.dumps({"error": f"Skill '{name}' not found."})

        shutil.rmtree(skill_dir)

        if self._invalidate:
            self._invalidate()

        logger.info("skill_manage.delete_completed: name={}", name)
        return f"Skill '{name}' deleted."

    async def _list(self, **kwargs: Any) -> str:
        """List all available skills.

        Args:
            **kwargs: Ignored.

        Returns:
            JSON list of skills with name, source, and availability.
        """
        skills = self._loader.list_skills(filter_unavailable=False)
        result = []
        for s in skills:
            meta = self._loader.get_skill_metadata(s["name"])
            desc = meta.get("description", s["name"]) if meta else s["name"]
            result.append(
                {
                    "name": s["name"],
                    "source": s["source"],
                    "description": desc,
                }
            )
        return json.dumps(result, indent=2)

    async def _read(self, name: str = "", **kwargs: Any) -> str:
        """Read a skill's content.

        Args:
            name: Skill name to read.
            **kwargs: Ignored.

        Returns:
            Skill content or error message.
        """
        if err := _validate_name(name):
            return json.dumps({"error": err})

        content = self._loader.load_skill(name)
        if content is None:
            return json.dumps({"error": f"Skill '{name}' not found."})

        return content
