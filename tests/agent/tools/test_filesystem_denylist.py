"""Tests for filesystem denylist path restriction."""

import pytest
from pathlib import Path

from velo.agent.tools.filesystem import _resolve_path


class TestResolvePath:
    def test_allows_normal_path(self, tmp_path):
        result = _resolve_path(str(tmp_path / "file.txt"), workspace=tmp_path)
        assert result == (tmp_path / "file.txt").resolve()

    def test_blocks_etc(self, tmp_path):
        with pytest.raises(PermissionError, match="restricted system directory"):
            _resolve_path("/etc/passwd", workspace=tmp_path)

    def test_blocks_etc_subdir(self, tmp_path):
        with pytest.raises(PermissionError, match="restricted system directory"):
            _resolve_path("/etc/ssh/sshd_config", workspace=tmp_path)

    def test_blocks_proc(self, tmp_path):
        with pytest.raises(PermissionError, match="restricted system directory"):
            _resolve_path("/proc/self/environ", workspace=tmp_path)

    def test_blocks_sys(self, tmp_path):
        with pytest.raises(PermissionError, match="restricted system directory"):
            _resolve_path("/sys/kernel", workspace=tmp_path)

    def test_blocks_dev(self, tmp_path):
        with pytest.raises(PermissionError, match="restricted system directory"):
            _resolve_path("/dev/null", workspace=tmp_path)

    def test_blocks_root_home(self, tmp_path):
        with pytest.raises(PermissionError, match="restricted system directory"):
            _resolve_path("/root/.bashrc", workspace=tmp_path)

    def test_allows_relative_in_workspace(self, tmp_path):
        # Relative path resolved against workspace is fine
        result = _resolve_path("subdir/file.txt", workspace=tmp_path)
        assert result == (tmp_path / "subdir" / "file.txt").resolve()

    def test_symlink_to_etc_blocked(self, tmp_path):
        """Symlink pointing outside workspace into /etc should be blocked."""
        link = tmp_path / "evil_link"
        try:
            link.symlink_to("/etc")
        except (OSError, PermissionError):
            pytest.skip("Cannot create symlink in this environment")
        with pytest.raises(PermissionError):
            _resolve_path(str(link), workspace=tmp_path)

    def test_allowed_dir_still_enforced(self, tmp_path):
        other = tmp_path.parent / "other"
        with pytest.raises(PermissionError, match="outside allowed directory"):
            _resolve_path(str(other), workspace=tmp_path, allowed_dir=tmp_path)
