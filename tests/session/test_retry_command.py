"""Tests for /retry session truncation."""

import pytest
from velo.session.manager import Session


def test_truncate_to_last_user_removes_exchange():
    """Removes all messages from last user message onward."""
    session = Session(key="test:1")
    session.messages = [
        {"role": "system", "content": "You are helpful"},
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there!"},
        {"role": "user", "content": "What is 2+2?"},
        {"role": "assistant", "content": None, "tool_calls": [{"id": "t1"}]},
        {"role": "tool", "content": "4", "tool_call_id": "t1"},
        {"role": "assistant", "content": "2+2 is 4"},
    ]
    original_text, remaining = session.truncate_to_last_user()
    assert original_text == "What is 2+2?"
    assert len(remaining) == 3  # system + first user + first assistant
    assert remaining[-1]["role"] == "assistant"
    assert remaining[-1]["content"] == "Hi there!"


def test_truncate_no_user_messages():
    """Returns None when there are no user messages to retry."""
    session = Session(key="test:1")
    session.messages = [{"role": "system", "content": "You are helpful"}]
    result, _ = session.truncate_to_last_user()
    assert result is None


def test_truncate_only_one_user_message():
    """With only one user message, removes everything after system."""
    session = Session(key="test:1")
    session.messages = [
        {"role": "system", "content": "You are helpful"},
        {"role": "user", "content": "Hi"},
        {"role": "assistant", "content": "Hello!"},
    ]
    original_text, remaining = session.truncate_to_last_user()
    assert original_text == "Hi"
    assert len(remaining) == 1  # just system
