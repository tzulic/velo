"""Tests for the contact-manager plugin."""

import json
import sys
from pathlib import Path

import pytest

# Add the plugin directory to the path so we can import it directly.
# The plugin is loaded via importlib at runtime, not installed as a package.
sys.path.insert(
    0,
    str(
        Path(__file__).resolve().parents[2]
        / "library"
        / "plugins"
        / "horizontal"
        / "contact-manager"
    ),
)

# ruff: noqa: E402
from __init__ import (  # type: ignore[import]
    AddContactTool,
    ContactStore,
    DedupeContactsTool,
    DeleteContactTool,
    EnrichContactTool,
    FindContactsTool,
    UpdateContactTool,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_store(
    tmp_path: Path,
    max_contacts: int = 10,
    auto_dedupe_on_add: bool = True,
) -> ContactStore:
    """Create a ContactStore backed by a temp file.

    Args:
        tmp_path: Pytest tmp_path fixture directory.
        max_contacts: Maximum contacts allowed. Default 10 (small for limit tests).
        auto_dedupe_on_add: Enable email dedupe on add. Default True.

    Returns:
        A fresh ContactStore instance.
    """
    return ContactStore(
        tmp_path / "contacts.json",
        max_contacts=max_contacts,
        auto_dedupe_on_add=auto_dedupe_on_add,
    )


def _add_contact(
    store: ContactStore,
    name: str = "John Smith",
    email: str = "john@acme.com",
    company: str = "Acme Corp",
    tags: str = "",
) -> dict:
    """Helper: add a contact, assert success, and return it."""
    result = store.add(name=name, email=email, company=company, tags=tags)
    assert isinstance(result, dict), f"Expected dict, got error: {result}"
    return result


# ---------------------------------------------------------------------------
# ContactStore: CRUD
# ---------------------------------------------------------------------------


class TestContactStoreCrud:
    """Tests for ContactStore add, get, update, delete."""

    def test_add_contact(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        c = _add_contact(store, name="Alice", email="alice@example.com")
        assert c["id"] == "CON-0001"
        assert c["name"] == "Alice"
        assert c["email"] == "alice@example.com"
        assert c["enriched"] is False

    def test_add_auto_increments_id(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        c1 = _add_contact(store, name="Alice", email="alice@example.com")
        c2 = _add_contact(store, name="Bob", email="bob@example.com")
        assert c1["id"] == "CON-0001"
        assert c2["id"] == "CON-0002"

    def test_add_persists_to_disk(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        _add_contact(store, name="Charlie", email="charlie@example.com")
        raw = json.loads((tmp_path / "contacts.json").read_text())
        assert len(raw) == 1
        assert raw[0]["name"] == "Charlie"

    def test_id_counter_survives_reload(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        _add_contact(store, name="A", email="a@x.com")
        _add_contact(store, name="B", email="b@x.com")
        store2 = _make_store(tmp_path)
        c3 = _add_contact(store2, name="C", email="c@x.com")
        assert c3["id"] == "CON-0003"

    def test_get_existing_contact(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        _add_contact(store, name="Dave", email="dave@example.com")
        contact = store.get("CON-0001")
        assert contact is not None
        assert contact["name"] == "Dave"

    def test_get_nonexistent_returns_none(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        assert store.get("CON-9999") is None

    def test_update_contact(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        _add_contact(store)
        updated = store.update("CON-0001", role="CTO", company="NewCorp")
        assert updated is not None
        assert updated["role"] == "CTO"
        assert updated["company"] == "NewCorp"

    def test_update_nonexistent_returns_none(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        result = store.update("CON-9999", role="CEO")
        assert result is None

    def test_delete_contact(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        _add_contact(store)
        assert store.delete("CON-0001") is True
        assert store.get("CON-0001") is None

    def test_delete_nonexistent_returns_false(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        assert store.delete("CON-9999") is False

    def test_tags_stored_as_list(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        result = store.add(name="Tagged", email="t@x.com", tags="hot,enterprise")
        assert isinstance(result, dict)
        assert result["tags"] == ["hot", "enterprise"]

    def test_update_tags_from_string(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        _add_contact(store)
        updated = store.update("CON-0001", tags="vip,warm")
        assert updated is not None
        assert updated["tags"] == ["vip", "warm"]


# ---------------------------------------------------------------------------
# ContactStore: email dedupe on add
# ---------------------------------------------------------------------------


class TestContactStoreEmailDedupe:
    """Tests for auto_dedupe_on_add behaviour."""

    def test_duplicate_email_blocked_when_enabled(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path, auto_dedupe_on_add=True)
        _add_contact(store, name="John", email="john@acme.com")
        result = store.add(name="J. Smith", email="john@acme.com")
        assert isinstance(result, str)
        assert "already exists" in result
        assert "CON-0001" in result

    def test_duplicate_email_allowed_when_disabled(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path, auto_dedupe_on_add=False)
        _add_contact(store, name="John", email="john@acme.com")
        result = store.add(name="J. Smith", email="john@acme.com")
        assert isinstance(result, dict)
        assert result["id"] == "CON-0002"

    def test_dedupe_check_is_case_insensitive(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path, auto_dedupe_on_add=True)
        _add_contact(store, name="John", email="John@ACME.COM")
        result = store.add(name="J. Smith", email="john@acme.com")
        assert isinstance(result, str)
        assert "already exists" in result

    def test_no_email_skips_dedupe_check(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path, auto_dedupe_on_add=True)
        r1 = store.add(name="Alice")
        r2 = store.add(name="Alice")
        assert isinstance(r1, dict)
        assert isinstance(r2, dict)


# ---------------------------------------------------------------------------
# ContactStore: max contacts enforcement
# ---------------------------------------------------------------------------


class TestContactStoreMaxContacts:
    """Tests for max_contacts limit."""

    def test_max_contacts_enforced(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path, max_contacts=2)
        _add_contact(store, name="A", email="a@x.com")
        _add_contact(store, name="B", email="b@x.com")
        result = store.add(name="C", email="c@x.com")
        assert isinstance(result, str)
        assert "limit reached" in result

    def test_max_contacts_error_shows_limit(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path, max_contacts=1)
        _add_contact(store, name="A", email="a@x.com")
        result = store.add(name="B", email="b@x.com")
        assert isinstance(result, str)
        assert "1" in result


# ---------------------------------------------------------------------------
# ContactStore: find / search
# ---------------------------------------------------------------------------


class TestContactStoreFind:
    """Tests for ContactStore.find() filtering."""

    def _populate(self, store: ContactStore) -> None:
        """Populate store with 3 contacts for search tests."""
        store.add(name="Alice Wonderland", email="alice@wonder.land", company="Wonderland", tags="hot")
        store.add(name="Bob Builder", email="bob@build.it", company="Builders Inc", tags="warm")
        store.add(name="Charlie Brown", email="charlie@peanuts.com", company="Wonderland", tags="hot")

    def test_find_by_name_substring(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        self._populate(store)
        results = store.find(query="alice")
        assert len(results) == 1
        assert results[0]["name"] == "Alice Wonderland"

    def test_find_by_email_substring(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        self._populate(store)
        results = store.find(query="build.it")
        assert len(results) == 1
        assert results[0]["name"] == "Bob Builder"

    def test_find_by_company_exact(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        self._populate(store)
        results = store.find(company="Wonderland")
        assert len(results) == 2

    def test_find_by_tag(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        self._populate(store)
        results = store.find(tag="hot")
        assert len(results) == 2

    def test_find_combined_filters(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        self._populate(store)
        # "alice" in name AND company "Wonderland" AND tag "hot"
        results = store.find(query="alice", company="Wonderland", tag="hot")
        assert len(results) == 1
        assert results[0]["name"] == "Alice Wonderland"

    def test_find_no_match_returns_empty(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        self._populate(store)
        results = store.find(query="nobody here")
        assert len(results) == 0

    def test_find_case_insensitive_query(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        self._populate(store)
        results = store.find(query="ALICE")
        assert len(results) == 1


# ---------------------------------------------------------------------------
# ContactStore: dedupe
# ---------------------------------------------------------------------------


class TestContactStoreDedupe:
    """Tests for ContactStore.dedupe()."""

    def test_dedupe_finds_email_match(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path, auto_dedupe_on_add=False)
        store.add(name="John Smith", email="john@acme.com", company="Acme")
        store.add(name="J. Smith", email="john@acme.com", company="Acme Co")
        groups = store.dedupe()
        assert len(groups) == 1
        assert len(groups[0]) == 2

    def test_dedupe_finds_name_company_match(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path, auto_dedupe_on_add=False)
        store.add(name="Sarah Connor", email="sarah@sky.net", company="Skynet")
        store.add(name="Sarah O'Connor", email="s.connor@sky.net", company="Skynet")
        groups = store.dedupe()
        assert len(groups) == 1
        assert len(groups[0]) == 2

    def test_dedupe_no_dupes(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        store.add(name="Alice", email="alice@x.com", company="Alpha Corp")
        store.add(name="Bob", email="bob@y.com", company="Beta Corp")
        groups = store.dedupe()
        assert groups == []

    def test_dedupe_skips_empty_company_for_name_match(self, tmp_path: Path) -> None:
        """Name-only match without company should NOT be flagged."""
        store = _make_store(tmp_path, auto_dedupe_on_add=False)
        store.add(name="Sarah Connor", email="a@x.com", company="")
        store.add(name="Sarah Connor", email="b@x.com", company="")
        groups = store.dedupe()
        assert groups == []


# ---------------------------------------------------------------------------
# ContactStore: enrich
# ---------------------------------------------------------------------------


class TestContactStoreEnrich:
    """Tests for ContactStore.enrich()."""

    def test_enrich_missing_fields(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        store.add(name="John Smith", email="john@acme.com")  # missing company, role, phone
        prompt = store.enrich("CON-0001")
        assert "missing" in prompt
        assert "company" in prompt
        assert "role" in prompt
        assert "phone" in prompt
        assert "web_search" in prompt

    def test_enrich_no_missing_fields(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        store.add(
            name="Full Person",
            email="full@example.com",
            company="Corp",
            role="CEO",
            phone="+1-555-0000",
        )
        prompt = store.enrich("CON-0001")
        assert "no missing fields" in prompt

    def test_enrich_not_found(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        result = store.enrich("CON-9999")
        assert "not found" in result


# ---------------------------------------------------------------------------
# ContactStore: context string
# ---------------------------------------------------------------------------


class TestContactStoreContextString:
    """Tests for get_summary() and context_string()."""

    def test_context_string_empty(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        assert store.context_string() == "Contacts: none"

    def test_context_string_with_contacts(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        store.add(name="Alice", email="alice@x.com", company="Corp")
        ctx = store.context_string()
        assert "1 total" in ctx

    def test_context_string_hot_count(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        store.add(name="Hot Lead", email="hot@x.com", company="Corp", tags="hot")
        store.add(name="Cold Lead", email="cold@x.com", company="Corp")
        ctx = store.context_string()
        assert "1 hot" in ctx

    def test_context_string_needs_enrichment(self, tmp_path: Path) -> None:
        """Contact with enriched=False and missing email should count."""
        store = _make_store(tmp_path)
        # Add with no email and no company — needs_enrichment = True (enriched defaults to False)
        store.add(name="Sparse Person", email="", company="")
        ctx = store.context_string()
        assert "need enrichment" in ctx

    def test_context_string_no_enrichment_needed_when_enriched_true(self, tmp_path: Path) -> None:
        """Contacts marked enriched=True should not count as needing enrichment."""
        store = _make_store(tmp_path)
        store.add(name="Enriched Person", email="", company="")
        # Manually mark as enriched
        store._contacts[0]["enriched"] = True
        store._save()
        ctx = store.context_string()
        assert "need enrichment" not in ctx


# ---------------------------------------------------------------------------
# Tool execute() methods
# ---------------------------------------------------------------------------


class TestContactTools:
    """Tests for tool execute() methods — success and error cases."""

    # -- AddContactTool --

    @pytest.mark.asyncio
    async def test_add_tool_success(self, tmp_path: Path) -> None:
        store = ContactStore(tmp_path / "contacts.json")
        tool = AddContactTool(store)
        result = await tool.execute(name="Jane Doe", email="jane@example.com")
        assert "CON-0001" in result
        assert "Jane Doe" in result

    @pytest.mark.asyncio
    async def test_add_tool_duplicate_email(self, tmp_path: Path) -> None:
        store = ContactStore(tmp_path / "contacts.json", auto_dedupe_on_add=True)
        tool = AddContactTool(store)
        await tool.execute(name="Jane", email="jane@example.com")
        result = await tool.execute(name="J. Doe", email="jane@example.com")
        assert "already exists" in result

    @pytest.mark.asyncio
    async def test_add_tool_max_reached(self, tmp_path: Path) -> None:
        store = ContactStore(tmp_path / "contacts.json", max_contacts=1)
        tool = AddContactTool(store)
        await tool.execute(name="First", email="first@x.com")
        result = await tool.execute(name="Second", email="second@x.com")
        assert "limit reached" in result

    # -- UpdateContactTool --

    @pytest.mark.asyncio
    async def test_update_tool_success(self, tmp_path: Path) -> None:
        store = ContactStore(tmp_path / "contacts.json")
        store.add(name="Original", email="orig@x.com")
        tool = UpdateContactTool(store)
        result = await tool.execute(contact_id="CON-0001", role="Engineer")
        assert "CON-0001" in result

    @pytest.mark.asyncio
    async def test_update_tool_not_found(self, tmp_path: Path) -> None:
        store = ContactStore(tmp_path / "contacts.json")
        tool = UpdateContactTool(store)
        result = await tool.execute(contact_id="CON-9999", role="Engineer")
        assert "not found" in result

    # -- DeleteContactTool --

    @pytest.mark.asyncio
    async def test_delete_tool_success(self, tmp_path: Path) -> None:
        store = ContactStore(tmp_path / "contacts.json")
        store.add(name="Delete Me", email="del@x.com")
        tool = DeleteContactTool(store)
        result = await tool.execute(contact_id="CON-0001")
        assert "Deleted" in result
        assert store.get("CON-0001") is None

    @pytest.mark.asyncio
    async def test_delete_tool_not_found(self, tmp_path: Path) -> None:
        store = ContactStore(tmp_path / "contacts.json")
        tool = DeleteContactTool(store)
        result = await tool.execute(contact_id="CON-9999")
        assert "not found" in result

    # -- FindContactsTool --

    @pytest.mark.asyncio
    async def test_find_tool_returns_matches(self, tmp_path: Path) -> None:
        store = ContactStore(tmp_path / "contacts.json")
        store.add(name="Bob", email="bob@x.com", company="BobCorp")
        tool = FindContactsTool(store)
        result = await tool.execute(query="bob")
        assert "CON-0001" in result
        assert "Bob" in result

    @pytest.mark.asyncio
    async def test_find_tool_no_results(self, tmp_path: Path) -> None:
        store = ContactStore(tmp_path / "contacts.json")
        tool = FindContactsTool(store)
        result = await tool.execute(query="nobody")
        assert "No contacts found" in result

    # -- EnrichContactTool --

    @pytest.mark.asyncio
    async def test_enrich_tool_missing_fields(self, tmp_path: Path) -> None:
        store = ContactStore(tmp_path / "contacts.json")
        store.add(name="Sparse", email="sparse@x.com")
        tool = EnrichContactTool(store)
        result = await tool.execute(contact_id="CON-0001")
        assert "missing" in result
        assert "web_search" in result

    @pytest.mark.asyncio
    async def test_enrich_tool_not_found(self, tmp_path: Path) -> None:
        store = ContactStore(tmp_path / "contacts.json")
        tool = EnrichContactTool(store)
        result = await tool.execute(contact_id="CON-9999")
        assert "not found" in result

    # -- DedupeContactsTool --

    @pytest.mark.asyncio
    async def test_dedupe_tool_finds_dupes(self, tmp_path: Path) -> None:
        store = ContactStore(tmp_path / "contacts.json", auto_dedupe_on_add=False)
        store.add(name="John Smith", email="john@acme.com", company="Acme")
        store.add(name="J. Smith", email="john@acme.com", company="Acme Co")
        tool = DedupeContactsTool(store)
        result = await tool.execute()
        assert "Group 1" in result
        assert "email match" in result
        assert "update_contact" in result

    @pytest.mark.asyncio
    async def test_dedupe_tool_no_dupes(self, tmp_path: Path) -> None:
        store = ContactStore(tmp_path / "contacts.json")
        store.add(name="Alice", email="alice@x.com", company="Alpha")
        tool = DedupeContactsTool(store)
        result = await tool.execute()
        assert "No duplicates found" in result
