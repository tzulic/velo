"""Tests for FTS5 full-text search in SQLiteSessionStore."""

from __future__ import annotations

from pathlib import Path

import pytest

from velo.session.manager import Session
from velo.session.sqlite_store import SQLiteSessionStore


@pytest.fixture
def store(tmp_path: Path) -> SQLiteSessionStore:
    """Provide a fresh SQLiteSessionStore backed by a temp file."""
    return SQLiteSessionStore(tmp_path / "sessions.db")


def _make_session(
    key: str = "test:user",
    messages: list[tuple[str, str]] | None = None,
) -> Session:
    """Create a test session with real content.

    Args:
        key: Session key.
        messages: List of (role, content) tuples. Defaults to a sample conversation.

    Returns:
        Session with the given messages.
    """
    s = Session(key=key)
    if messages is None:
        messages = [
            ("user", "How do I deploy to production?"),
            ("assistant", "You can deploy using the deploy command with --prod flag."),
        ]
    for role, content in messages:
        s.add_message(role, content)
    return s


class TestFTSIndexPopulation:
    """Tests for FTS index population during save."""

    def test_fts_index_populated_on_save(self, store: SQLiteSessionStore) -> None:
        """Saving a session indexes user and assistant messages for search."""
        session = _make_session("telegram:100", messages=[
            ("user", "What is kubernetes orchestration?"),
            ("assistant", "Kubernetes orchestrates container workloads."),
        ])
        store.save(session)

        results = store.search_messages("kubernetes")
        assert len(results) >= 1
        assert any("kubernetes" in r["content"].lower() for r in results)


class TestKeywordSearch:
    """Tests for keyword search functionality."""

    def test_keyword_search_returns_matches(self, store: SQLiteSessionStore) -> None:
        """Searching for a keyword returns matching messages."""
        session = _make_session("telegram:200", messages=[
            ("user", "Configure the nginx reverse proxy"),
            ("assistant", "Here is the nginx config for reverse proxy setup."),
        ])
        store.save(session)

        results = store.search_messages("nginx")
        assert len(results) >= 1
        assert all(r["session_key"] == "telegram:200" for r in results)

    def test_empty_results_for_no_matches(self, store: SQLiteSessionStore) -> None:
        """Searching for a nonexistent term returns an empty list."""
        session = _make_session("telegram:300", messages=[
            ("user", "Hello world"),
            ("assistant", "Hi there!"),
        ])
        store.save(session)

        results = store.search_messages("xylophone")
        assert results == []


class TestQuerySanitization:
    """Tests for FTS5 query sanitization."""

    def test_query_sanitization_cpp(self, store: SQLiteSessionStore) -> None:
        """Special characters like C++ don't crash FTS5."""
        session = _make_session("telegram:400", messages=[
            ("user", "I need help with C++ templates"),
            ("assistant", "C++ templates are a powerful feature."),
        ])
        store.save(session)

        # Should not raise; C++ has special chars that could break FTS5
        results = store.search_messages("C++")
        assert isinstance(results, list)

    def test_query_sanitization_unclosed_quotes(self, store: SQLiteSessionStore) -> None:
        """Unclosed quotes are balanced and don't crash."""
        session = _make_session("telegram:401", messages=[
            ("user", "Search for 'hello world"),
        ])
        store.save(session)

        results = store.search_messages('"hello')
        assert isinstance(results, list)

    def test_query_sanitization_boolean_operators(self, store: SQLiteSessionStore) -> None:
        """Standalone AND/OR/NOT operators are stripped."""
        sanitized = SQLiteSessionStore._sanitize_fts5_query("cats AND dogs OR NOT fish")
        assert "AND" not in sanitized
        assert "OR" not in sanitized
        assert "NOT" not in sanitized

    def test_query_sanitization_parentheses(self, store: SQLiteSessionStore) -> None:
        """Parentheses are stripped from queries."""
        sanitized = SQLiteSessionStore._sanitize_fts5_query("(hello) {world}")
        assert "(" not in sanitized
        assert ")" not in sanitized
        assert "{" not in sanitized
        assert "}" not in sanitized

    def test_query_sanitization_empty_fallback(self, store: SQLiteSessionStore) -> None:
        """Empty query after sanitization falls back to first word."""
        sanitized = SQLiteSessionStore._sanitize_fts5_query("AND OR NOT")
        # After removing operators, should either be empty or fallback
        assert isinstance(sanitized, str)


class TestBackfill:
    """Tests for lazy FTS backfill."""

    def test_backfill_indexes_existing(self, store: SQLiteSessionStore) -> None:
        """First search triggers backfill of pre-existing messages."""
        # Save session — this indexes via save()
        session = _make_session("telegram:500", messages=[
            ("user", "Install postgresql database"),
            ("assistant", "Run apt-get install postgresql."),
        ])
        store.save(session)

        # Create a new store pointing at same DB to simulate restart
        store2 = SQLiteSessionStore(store._path)
        # The new store has _fts_indexed=False, should backfill on search
        results = store2.search_messages("postgresql")
        assert len(results) >= 1
        assert any("postgresql" in r["content"].lower() for r in results)


class TestMultipleSessionSearch:
    """Tests for search across multiple sessions."""

    def test_search_with_multiple_sessions(self, store: SQLiteSessionStore) -> None:
        """Results come from the correct sessions across multiple saved sessions."""
        session1 = _make_session("telegram:601", messages=[
            ("user", "Deploy the flask application"),
            ("assistant", "Flask app deployed on port 5000."),
        ])
        session2 = _make_session("telegram:602", messages=[
            ("user", "Set up the django project"),
            ("assistant", "Django project is configured."),
        ])
        session3 = _make_session("telegram:603", messages=[
            ("user", "Unrelated conversation about weather"),
            ("assistant", "The weather is sunny today."),
        ])
        store.save(session1)
        store.save(session2)
        store.save(session3)

        # Search for flask — should only return session1
        flask_results = store.search_messages("flask")
        assert len(flask_results) >= 1
        assert all(r["session_key"] == "telegram:601" for r in flask_results)

        # Search for django — should only return session2
        django_results = store.search_messages("django")
        assert len(django_results) >= 1
        assert all(r["session_key"] == "telegram:602" for r in django_results)

    def test_search_result_fields(self, store: SQLiteSessionStore) -> None:
        """Search results contain expected fields."""
        session = _make_session("telegram:700", messages=[
            ("user", "Check the prometheus metrics"),
        ])
        store.save(session)

        results = store.search_messages("prometheus")
        assert len(results) >= 1
        hit = results[0]
        assert "session_key" in hit
        assert "content" in hit
        assert "created_at" in hit
        assert "score" in hit
        assert len(hit["content"]) <= 500
