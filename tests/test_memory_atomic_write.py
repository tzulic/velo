"""Tests for atomic file writes in MemoryStore."""

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from velo.agent.memory import _atomic_write


class TestAtomicWrite:
    """Unit tests for _atomic_write()."""

    def test_writes_content_to_file(self, tmp_path: Path) -> None:
        """_atomic_write creates the file with correct content."""
        path = tmp_path / "test.md"
        _atomic_write(path, "hello world")
        assert path.read_text(encoding="utf-8") == "hello world"

    def test_overwrites_existing_file(self, tmp_path: Path) -> None:
        """_atomic_write replaces an existing file atomically."""
        path = tmp_path / "test.md"
        path.write_text("original", encoding="utf-8")
        _atomic_write(path, "new content")
        assert path.read_text(encoding="utf-8") == "new content"

    def test_leaves_original_intact_on_fsync_failure(self, tmp_path: Path) -> None:
        """If fsync raises, original file is not modified and temp file is cleaned up."""
        path = tmp_path / "test.md"
        original_content = "original content"
        path.write_text(original_content, encoding="utf-8")

        with patch("os.fsync", side_effect=OSError("disk full")):
            with pytest.raises(OSError, match="disk full"):
                _atomic_write(path, "new content that should not appear")

        # Original file must be intact
        assert path.read_text(encoding="utf-8") == original_content

        # No leftover temp files
        tmp_files = list(tmp_path.glob(".mem_*.tmp"))
        assert len(tmp_files) == 0, f"Temp files not cleaned up: {tmp_files}"

    def test_leaves_original_intact_on_write_failure(self, tmp_path: Path) -> None:
        """If write fails, original file is not modified."""
        path = tmp_path / "test.md"
        original_content = "original"
        path.write_text(original_content, encoding="utf-8")

        with patch("os.fdopen", side_effect=OSError("write error")):
            with pytest.raises(OSError):
                _atomic_write(path, "should not appear")

        assert path.read_text(encoding="utf-8") == original_content

    def test_no_temp_files_after_success(self, tmp_path: Path) -> None:
        """No temp files remain after a successful write."""
        path = tmp_path / "test.md"
        _atomic_write(path, "content")
        tmp_files = list(tmp_path.glob(".mem_*.tmp"))
        assert len(tmp_files) == 0

    def test_unicode_content_roundtrip(self, tmp_path: Path) -> None:
        """Unicode content (including emoji and CJK) is written and read correctly."""
        path = tmp_path / "test.md"
        content = "# Memory\n\nUser: 李明 🎯\nPreference: UTF-8 everywhere"
        _atomic_write(path, content)
        assert path.read_text(encoding="utf-8") == content

    def test_empty_content(self, tmp_path: Path) -> None:
        """Empty string is written correctly."""
        path = tmp_path / "test.md"
        _atomic_write(path, "")
        assert path.read_text(encoding="utf-8") == ""

    def test_temp_file_in_same_directory(self, tmp_path: Path) -> None:
        """Temp file is created in same directory as target (required for atomic rename)."""
        path = tmp_path / "test.md"
        created_tmp: list[Path] = []
        original_replace = os.replace

        def _capture_replace(src: str, dst: str) -> None:
            created_tmp.append(Path(src))
            original_replace(src, dst)

        with patch("os.replace", side_effect=_capture_replace):
            _atomic_write(path, "content")

        if created_tmp:
            # Temp file was in same directory
            assert created_tmp[0].parent == tmp_path


class TestMemoryStoreAtomicWrites:
    """Integration tests verifying MemoryStore uses atomic writes."""

    def test_write_long_term_atomic_on_failure(self, tmp_path: Path) -> None:
        """write_long_term leaves original intact when fsync fails."""
        from velo.agent.memory import MemoryStore

        store = MemoryStore(tmp_path)
        original = "# Memory\n\nOriginal content."
        store.write_long_term(original)

        with patch("os.fsync", side_effect=OSError("disk full")):
            with pytest.raises(OSError):
                store.write_long_term("# Memory\n\nReplacement that should fail.")

        assert store.memory_file.read_text(encoding="utf-8") == original

    def test_write_user_profile_atomic_on_failure(self, tmp_path: Path) -> None:
        """write_user_profile leaves original intact when fsync fails."""
        from velo.agent.memory import MemoryStore

        store = MemoryStore(tmp_path)
        original = "# User Profile\n\nAlice, UTC+1."
        store.write_user_profile(original)

        with patch("os.fsync", side_effect=OSError("disk full")):
            with pytest.raises(OSError):
                store.write_user_profile("# User Profile\n\nReplacement.")

        assert store.user_file.read_text(encoding="utf-8") == original
