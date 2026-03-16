"""Contact manager plugin — persistent contact database with enrichment and dedupe.

Tools registered:
    add_contact     — add a new contact with auto-generated ID
    update_contact  — update fields on an existing contact
    delete_contact  — permanently remove a contact
    find_contacts   — search by name/email/company/tag
    enrich_contact  — return a prompt for enriching missing fields
    dedupe_contacts — find groups of potential duplicate contacts

Context provider:
    One-line summary: "Contacts: 47 total (12 hot, 8 need enrichment)"

Config keys:
    max_contacts (int): Maximum contacts allowed. Default 500.
    auto_dedupe_on_add (bool): Check for email duplicates on add. Default True.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from velo.agent.tools.base import Tool
from velo.plugins.types import PluginContext
from velo.utils.helpers import atomic_write

logger = logging.getLogger(__name__)


class ContactStore:
    """JSON-backed contact storage with query, dedupe, and enrichment capabilities.

    Args:
        path: Path to contacts.json file.
        max_contacts: Maximum number of contacts allowed.
        auto_dedupe_on_add: If True, block adding a contact with a duplicate email.
    """

    def __init__(
        self,
        path: Path,
        max_contacts: int = 500,
        auto_dedupe_on_add: bool = True,
    ) -> None:
        self._path = path
        self._max_contacts = max_contacts
        self._auto_dedupe_on_add = auto_dedupe_on_add
        self._contacts: list[dict[str, Any]] = []
        self._next_id = 1
        self._load()

    def _load(self) -> None:
        """Load contacts from disk."""
        if self._path.is_file():
            try:
                self._contacts = json.loads(self._path.read_text(encoding="utf-8"))
                if self._contacts:
                    max_num = max(
                        int(c["id"].split("-")[1]) for c in self._contacts
                    )
                    self._next_id = max_num + 1
            except (json.JSONDecodeError, KeyError, ValueError):
                logger.warning("contact_manager.load_failed: %s", self._path)
                self._contacts = []

    def _save(self) -> None:
        """Write contacts to disk atomically."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(self._path, json.dumps(self._contacts, indent=2, ensure_ascii=False))

    def _now_iso(self) -> str:
        """Return current UTC time as ISO string."""
        return datetime.now(timezone.utc).isoformat()

    def add(
        self,
        name: str,
        email: str = "",
        company: str = "",
        role: str = "",
        phone: str = "",
        industry: str = "",
        company_size: str = "",
        source: str = "",
        tags: str = "",
        notes: str = "",
    ) -> dict[str, Any] | str:
        """Add a new contact.

        Checks email dedupe if auto_dedupe_on_add is enabled. Returns the new
        contact dict on success, or an error string on failure.

        Args:
            name: Contact full name.
            email: Email address (used for dedupe).
            company: Company or organisation name.
            role: Job title or role.
            phone: Phone number.
            industry: Industry sector.
            company_size: Company size range (e.g. "50-200").
            source: Lead source (e.g. "inbound", "conference").
            tags: Comma-separated tags (e.g. "hot,enterprise").
            notes: Free-form notes.

        Returns:
            New contact dict, or an error string if limit reached or duplicate found.
        """
        if len(self._contacts) >= self._max_contacts:
            return f"Contact limit reached ({self._max_contacts}). Remove unused contacts first."

        # Email dedupe check
        if self._auto_dedupe_on_add and email:
            for c in self._contacts:
                if c.get("email", "").lower() == email.lower():
                    return (
                        f"Contact with email '{email}' already exists: "
                        f"{c['id']} — {c['name']}. Use update_contact to modify."
                    )

        now = self._now_iso()
        tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []

        contact: dict[str, Any] = {
            "id": f"CON-{self._next_id:04d}",
            "name": name,
            "email": email,
            "company": company,
            "role": role,
            "phone": phone,
            "industry": industry,
            "company_size": company_size,
            "source": source,
            "tags": tag_list,
            "enriched": False,
            "notes": notes,
            "last_contacted_at": "",
            "created_at": now,
            "updated_at": now,
        }
        self._next_id += 1
        self._contacts.append(contact)
        self._save()
        return contact

    def update(self, contact_id: str, **fields: Any) -> dict[str, Any] | None:
        """Update a contact by ID.

        Args:
            contact_id: Contact ID (e.g. CON-0001).
            **fields: Fields to update. Tags may be passed as a comma-separated
                string and will be converted to a list.

        Returns:
            Updated contact dict, or None if not found.
        """
        for contact in self._contacts:
            if contact["id"] == contact_id:
                for key, value in fields.items():
                    if value is not None and value != "" and key in contact:
                        # Reason: tags come in as comma-separated strings from tool calls
                        if key == "tags" and isinstance(value, str):
                            contact[key] = [t.strip() for t in value.split(",") if t.strip()]
                        else:
                            contact[key] = value
                contact["updated_at"] = self._now_iso()
                self._save()
                return contact
        return None

    def delete(self, contact_id: str) -> bool:
        """Delete a contact by ID.

        Args:
            contact_id: Contact ID (e.g. CON-0001).

        Returns:
            True if deleted, False if not found.
        """
        for i, contact in enumerate(self._contacts):
            if contact["id"] == contact_id:
                self._contacts.pop(i)
                self._save()
                return True
        return False

    def get(self, contact_id: str) -> dict[str, Any] | None:
        """Get a single contact by ID.

        Args:
            contact_id: Contact ID (e.g. CON-0001).

        Returns:
            Contact dict if found, None otherwise.
        """
        for contact in self._contacts:
            if contact["id"] == contact_id:
                return contact
        return None

    def find(
        self,
        query: str = "",
        company: str = "",
        tag: str = "",
    ) -> list[dict[str, Any]]:
        """Search contacts with optional filters.

        Applies all non-empty filters as AND conditions.

        Args:
            query: Case-insensitive substring match on name or email.
            company: Exact (case-insensitive) company filter.
            tag: Exact (case-insensitive) tag filter.

        Returns:
            List of matching contact dicts.
        """
        results = self._contacts

        if query:
            q = query.lower()
            results = [
                c for c in results
                if q in c.get("name", "").lower() or q in c.get("email", "").lower()
            ]

        if company:
            co = company.lower()
            results = [c for c in results if c.get("company", "").lower() == co]

        if tag:
            tl = tag.lower()
            results = [c for c in results if tl in [t.lower() for t in c.get("tags", [])]]

        return results

    def enrich(self, contact_id: str) -> str:
        """Return an enrichment prompt listing missing fields for a contact.

        Does NOT perform any search — the agent uses its own tools (e.g. web_search
        or Composio LinkedIn) to gather the information.

        Args:
            contact_id: Contact ID (e.g. CON-0001).

        Returns:
            Formatted enrichment prompt, or error string if not found.
        """
        contact = self.get(contact_id)
        if contact is None:
            return f"Contact {contact_id} not found."

        missing = []
        if not contact.get("company"):
            missing.append("company")
        if not contact.get("role"):
            missing.append("role")
        if not contact.get("phone"):
            missing.append("phone")

        if not missing:
            return f"Contact {contact_id} ({contact['name']}) has no missing fields."

        lines = [
            f"Contact {contact_id} ({contact['name']}) is missing: {', '.join(missing)}.",
            "Suggested searches:",
        ]
        name = contact["name"]
        email = contact.get("email", "")
        if "role" in missing or "company" in missing:
            lines.append(f'  - "{name} LinkedIn" for role and company')
        if email and "company" in missing:
            lines.append(f'  - "{email}" for company website')
        lines.append(
            "Use web_search to find this information, then update_contact to save it."
        )
        return "\n".join(lines)

    def dedupe(self) -> list[list[dict[str, Any]]]:
        """Find groups of potential duplicate contacts.

        Matching rules:
          - Exact email match (case-insensitive, non-empty)
          - Same first name (case-insensitive) AND same company (case-insensitive, non-empty)

        Returns:
            List of duplicate groups. Each group is a list of 2+ contact dicts.
        """
        groups: list[list[dict[str, Any]]] = []
        matched_ids: set[str] = set()

        contacts = self._contacts

        # Email matching pass
        email_map: dict[str, list[dict[str, Any]]] = {}
        for c in contacts:
            email = c.get("email", "").strip().lower()
            if email:
                email_map.setdefault(email, []).append(c)

        for email, group in email_map.items():
            if len(group) >= 2:
                groups.append(list(group))
                for c in group:
                    matched_ids.add(c["id"])

        # Name + company matching pass (only for unmatched contacts)
        name_company_map: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for c in contacts:
            if c["id"] in matched_ids:
                continue
            first_name = c.get("name", "").split()[0].lower() if c.get("name") else ""
            company = c.get("company", "").strip().lower()
            if first_name and company:
                key = (first_name, company)
                name_company_map.setdefault(key, []).append(c)

        for key, group in name_company_map.items():
            if len(group) >= 2:
                groups.append(list(group))

        return groups

    def get_summary(self) -> dict[str, int]:
        """Get contact counts for context provider (single-pass).

        "hot" = contact has the tag "hot".
        "needs_enrichment" = enriched is False AND (email or company is empty).

        Returns:
            Dict with total, hot, and needs_enrichment counts.
        """
        total = 0
        hot = 0
        needs_enrichment = 0

        for c in self._contacts:
            total += 1
            if "hot" in [t.lower() for t in c.get("tags", [])]:
                hot += 1
            if not c.get("enriched", True) and (
                not c.get("email") or not c.get("company")
            ):
                needs_enrichment += 1

        return {"total": total, "hot": hot, "needs_enrichment": needs_enrichment}

    def context_string(self) -> str:
        """One-line context for system prompt injection.

        Returns:
            Summary string like "Contacts: 47 total (12 hot, 8 need enrichment)".
        """
        s = self.get_summary()
        if s["total"] == 0:
            return "Contacts: none"
        parts: list[str] = []
        if s["hot"]:
            parts.append(f"{s['hot']} hot")
        if s["needs_enrichment"]:
            parts.append(f"{s['needs_enrichment']} need enrichment")
        suffix = f" ({', '.join(parts)})" if parts else ""
        return f"Contacts: {s['total']} total{suffix}"


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


class AddContactTool(Tool):
    """Tool: add a new contact.

    Args:
        store: ContactStore instance to write to.
    """

    def __init__(self, store: ContactStore) -> None:
        self._store = store

    @property
    def name(self) -> str:
        """Tool name."""
        return "add_contact"

    @property
    def description(self) -> str:
        """Tool description."""
        return (
            "Add a new contact to the local contact database. "
            "Auto-generates an ID (CON-0001). "
            "Checks for duplicate email if auto-dedupe is enabled."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        """JSON Schema for tool parameters."""
        return {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Contact full name"},
                "email": {"type": "string", "default": "", "description": "Email address"},
                "company": {"type": "string", "default": "", "description": "Company name"},
                "role": {"type": "string", "default": "", "description": "Job title or role"},
                "phone": {"type": "string", "default": "", "description": "Phone number"},
                "industry": {"type": "string", "default": "", "description": "Industry sector"},
                "company_size": {
                    "type": "string",
                    "default": "",
                    "description": "Company size range (e.g. '50-200')",
                },
                "source": {
                    "type": "string",
                    "default": "",
                    "description": "Lead source (e.g. 'inbound', 'conference')",
                },
                "tags": {
                    "type": "string",
                    "default": "",
                    "description": "Comma-separated tags (e.g. 'hot,enterprise')",
                },
                "notes": {"type": "string", "default": "", "description": "Free-form notes"},
            },
            "required": ["name"],
        }

    async def execute(self, **kwargs: Any) -> str:
        """Add a contact and return confirmation or error.

        Args:
            **kwargs: name (str) required; email, company, role, phone,
                      industry, company_size, source, tags, notes optional.

        Returns:
            Confirmation string or error message.
        """
        name = str(kwargs.get("name", ""))
        result = self._store.add(
            name=name,
            email=str(kwargs.get("email", "")),
            company=str(kwargs.get("company", "")),
            role=str(kwargs.get("role", "")),
            phone=str(kwargs.get("phone", "")),
            industry=str(kwargs.get("industry", "")),
            company_size=str(kwargs.get("company_size", "")),
            source=str(kwargs.get("source", "")),
            tags=str(kwargs.get("tags", "")),
            notes=str(kwargs.get("notes", "")),
        )
        if isinstance(result, str):
            # Error string returned by store
            return result
        return f"Added: {result['id']} — {result['name']} ({result['email'] or 'no email'})"


class UpdateContactTool(Tool):
    """Tool: update an existing contact.

    Args:
        store: ContactStore instance to write to.
    """

    def __init__(self, store: ContactStore) -> None:
        self._store = store

    @property
    def name(self) -> str:
        """Tool name."""
        return "update_contact"

    @property
    def description(self) -> str:
        """Tool description."""
        return (
            "Update one or more fields on an existing contact. "
            "Use contact ID (e.g. CON-0001)."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        """JSON Schema for tool parameters."""
        return {
            "type": "object",
            "properties": {
                "contact_id": {
                    "type": "string",
                    "description": "Contact ID (e.g. CON-0001)",
                },
                "name": {"type": "string", "default": ""},
                "email": {"type": "string", "default": ""},
                "company": {"type": "string", "default": ""},
                "role": {"type": "string", "default": ""},
                "phone": {"type": "string", "default": ""},
                "industry": {"type": "string", "default": ""},
                "company_size": {"type": "string", "default": ""},
                "source": {"type": "string", "default": ""},
                "tags": {
                    "type": "string",
                    "default": "",
                    "description": "Comma-separated tags",
                },
                "notes": {"type": "string", "default": ""},
                "enriched": {
                    "type": "boolean",
                    "description": "Mark contact as enriched",
                },
                "last_contacted_at": {
                    "type": "string",
                    "default": "",
                    "description": "ISO datetime of last contact",
                },
            },
            "required": ["contact_id"],
        }

    async def execute(self, **kwargs: Any) -> str:
        """Update a contact and return confirmation.

        Args:
            **kwargs: contact_id (str) required; any other field optional.

        Returns:
            Confirmation string or error message.
        """
        contact_id = str(kwargs.get("contact_id", ""))
        fields = {k: v for k, v in kwargs.items() if k != "contact_id" and v not in ("", None)}
        contact = self._store.update(contact_id, **fields)
        if contact is None:
            return f"Contact {contact_id} not found."
        return (
            f"Updated: {contact['id']} — {contact['name']} "
            f"({contact.get('company', '') or 'no company'})"
        )


class DeleteContactTool(Tool):
    """Tool: permanently remove a contact.

    Args:
        store: ContactStore instance to write to.
    """

    def __init__(self, store: ContactStore) -> None:
        self._store = store

    @property
    def name(self) -> str:
        """Tool name."""
        return "delete_contact"

    @property
    def description(self) -> str:
        """Tool description."""
        return "Permanently delete a contact by their ID."

    @property
    def parameters(self) -> dict[str, Any]:
        """JSON Schema for tool parameters."""
        return {
            "type": "object",
            "properties": {
                "contact_id": {
                    "type": "string",
                    "description": "Contact ID to delete (e.g. CON-0001)",
                },
            },
            "required": ["contact_id"],
        }

    async def execute(self, **kwargs: Any) -> str:
        """Delete a contact by ID.

        Args:
            **kwargs: contact_id (str) required.

        Returns:
            Confirmation string or error message.
        """
        contact_id = str(kwargs.get("contact_id", ""))
        if self._store.delete(contact_id):
            return f"Deleted contact {contact_id}."
        return f"Contact {contact_id} not found."


class FindContactsTool(Tool):
    """Tool: search contacts by name, email, company, or tag.

    Args:
        store: ContactStore instance to read from.
    """

    def __init__(self, store: ContactStore) -> None:
        self._store = store

    @property
    def name(self) -> str:
        """Tool name."""
        return "find_contacts"

    @property
    def description(self) -> str:
        """Tool description."""
        return (
            "Search contacts by name or email (substring), company (exact), or tag (exact). "
            "All filters are combined as AND conditions."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        """JSON Schema for tool parameters."""
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "default": "",
                    "description": "Substring search on name or email",
                },
                "company": {
                    "type": "string",
                    "default": "",
                    "description": "Exact company name filter",
                },
                "tag": {
                    "type": "string",
                    "default": "",
                    "description": "Exact tag filter",
                },
            },
            "required": [],
        }

    async def execute(self, **kwargs: Any) -> str:
        """Search contacts and return a formatted list.

        Args:
            **kwargs: query (str), company (str), tag (str) — all optional.

        Returns:
            Formatted contact list or "No contacts found."
        """
        contacts = self._store.find(
            query=str(kwargs.get("query", "")),
            company=str(kwargs.get("company", "")),
            tag=str(kwargs.get("tag", "")),
        )
        if not contacts:
            return "No contacts found."
        lines = [f"Found {len(contacts)} contact(s):\n"]
        for c in contacts:
            tags_str = f" [{', '.join(c['tags'])}]" if c.get("tags") else ""
            company_str = f" @ {c['company']}" if c.get("company") else ""
            role_str = f", {c['role']}" if c.get("role") else ""
            lines.append(
                f"  {c['id']} — {c['name']}{company_str}{role_str} ({c.get('email') or 'no email'}){tags_str}"
            )
        return "\n".join(lines)


class EnrichContactTool(Tool):
    """Tool: get an enrichment prompt for a contact's missing fields.

    Args:
        store: ContactStore instance to read from.
    """

    def __init__(self, store: ContactStore) -> None:
        self._store = store

    @property
    def name(self) -> str:
        """Tool name."""
        return "enrich_contact"

    @property
    def description(self) -> str:
        """Tool description."""
        return (
            "Identify missing fields on a contact and return suggested searches. "
            "Does not perform the search itself — use web_search or LinkedIn tools to gather data."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        """JSON Schema for tool parameters."""
        return {
            "type": "object",
            "properties": {
                "contact_id": {
                    "type": "string",
                    "description": "Contact ID (e.g. CON-0001)",
                },
            },
            "required": ["contact_id"],
        }

    async def execute(self, **kwargs: Any) -> str:
        """Return enrichment prompt for a contact.

        Args:
            **kwargs: contact_id (str) required.

        Returns:
            Enrichment prompt string or error message.
        """
        contact_id = str(kwargs.get("contact_id", ""))
        return self._store.enrich(contact_id)


class DedupeContactsTool(Tool):
    """Tool: find groups of potential duplicate contacts.

    Args:
        store: ContactStore instance to read from.
    """

    def __init__(self, store: ContactStore) -> None:
        self._store = store

    @property
    def name(self) -> str:
        """Tool name."""
        return "dedupe_contacts"

    @property
    def description(self) -> str:
        """Tool description."""
        return (
            "Scan all contacts for potential duplicates. "
            "Matches on exact email OR same first name + same company. "
            "Does not auto-merge — agent reviews and decides."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        """JSON Schema for tool parameters."""
        return {
            "type": "object",
            "properties": {},
            "required": [],
        }

    async def execute(self, **kwargs: Any) -> str:
        """Find and report duplicate contact groups.

        Args:
            **kwargs: No parameters.

        Returns:
            Formatted duplicate groups, or "No duplicates found."
        """
        groups = self._store.dedupe()
        if not groups:
            return "No duplicates found."

        lines = [f"Found {len(groups)} duplicate group(s):\n"]
        for i, group in enumerate(groups, 1):
            # Determine match reason
            emails = [c.get("email", "").lower() for c in group if c.get("email")]
            if len(set(emails)) == 1 and emails:
                reason = "email match"
            else:
                reason = "name+company match"
            lines.append(f"Group {i} ({reason}):")
            for c in group:
                company_str = f", {c['company']}" if c.get("company") else ""
                email_str = c.get("email") or "no email"
                lines.append(f"  {c['id']}: {c['name']} ({email_str}{company_str})")
            lines.append("")

        lines.append("Use update_contact to merge and delete_contact to remove duplicates.")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Plugin entry point
# ---------------------------------------------------------------------------


def register(ctx: PluginContext) -> None:
    """Plugin entry point — register contact tools and context provider.

    Args:
        ctx: Plugin context with config and workspace.
    """
    max_contacts = int(ctx.config.get("max_contacts", 500))
    auto_dedupe_on_add = bool(ctx.config.get("auto_dedupe_on_add", True))

    store = ContactStore(
        path=ctx.workspace / "contacts.json",
        max_contacts=max_contacts,
        auto_dedupe_on_add=auto_dedupe_on_add,
    )

    ctx.register_tool(AddContactTool(store))
    ctx.register_tool(UpdateContactTool(store))
    ctx.register_tool(DeleteContactTool(store))
    ctx.register_tool(FindContactsTool(store))
    ctx.register_tool(EnrichContactTool(store))
    ctx.register_tool(DedupeContactsTool(store))
    ctx.add_context_provider(store.context_string)

    logger.debug(
        "contact_manager.register: max_contacts=%d, auto_dedupe_on_add=%s",
        max_contacts,
        auto_dedupe_on_add,
    )
