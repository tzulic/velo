"""Docker sandbox for isolated command execution."""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

from loguru import logger

from velo.config.schema import ExecToolConfig


def _check_docker() -> bool:
    """Check if Docker CLI is available on PATH.

    Returns:
        bool: True if the docker binary is found, False otherwise.
    """
    return shutil.which("docker") is not None


class DockerSandbox:
    """Executes commands in an isolated Docker container.

    Mounts the agent workspace read-only at /workspace inside the container.
    Resource limits (CPU, memory, network) are applied via docker run flags.

    Args:
        config: Exec tool configuration with sandbox settings.
        workspace: Agent workspace directory to mount read-only.
    """

    def __init__(self, config: ExecToolConfig, workspace: Path) -> None:
        """Initialize DockerSandbox with config and workspace.

        Args:
            config: ExecToolConfig containing docker_* settings.
            workspace: Path to the agent workspace directory.
        """
        self._config = config
        self._workspace = workspace
        self._container_id: str | None = None

    async def execute(self, command: str, timeout: int | None = None) -> tuple[str, int]:
        """Run command inside a Docker container and return output and exit code.

        Spawns an ephemeral container via `docker run --rm` with CPU, memory,
        and network limits from config. Kills the subprocess on timeout.

        Args:
            command: Shell command to execute inside the container.
            timeout: Per-command timeout in seconds. Defaults to docker_timeout from config.

        Returns:
            tuple[str, int]: (stdout+stderr combined, exit_code). Exit code -9 on timeout, 1 on error.

        Raises:
            RuntimeError: If Docker is not available on this host.
        """
        if not _check_docker():
            raise RuntimeError("Docker is not available. Install Docker or set sandbox='off'.")

        effective_timeout = timeout if timeout is not None else self._config.docker_timeout

        docker_cmd = [
            "docker",
            "run",
            "--rm",
            "--cpus",
            str(self._config.docker_cpu_limit),
            "--memory",
            self._config.docker_memory_limit,
            "--network",
            self._config.docker_network,
            "-v",
            f"{self._workspace}:/workspace:ro",
            "-w",
            "/workspace",
            self._config.docker_image,
            "sh",
            "-c",
            command,
        ]

        try:
            proc = await asyncio.create_subprocess_exec(
                *docker_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )

            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=effective_timeout)
            output = stdout.decode("utf-8", errors="replace") if stdout else ""
            return output, proc.returncode or 0

        except asyncio.TimeoutError:
            logger.warning("sandbox.timeout: command exceeded {}s", effective_timeout)
            try:
                proc.kill()  # type: ignore[possibly-undefined]
            except ProcessLookupError:
                pass
            return f"Command timed out after {effective_timeout}s", -9

        except Exception as exc:
            logger.error("sandbox.execute_failed: {}", exc)
            return f"Sandbox error: {exc}", 1

    async def cleanup(self) -> None:
        """Remove any lingering container state.

        If a named container ID was stored (e.g. for long-running containers),
        it is force-removed. No-op if no container ID is set.
        """
        if self._container_id:
            try:
                proc = await asyncio.create_subprocess_exec(
                    "docker",
                    "rm",
                    "-f",
                    self._container_id,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await proc.wait()
            except Exception:
                pass
            self._container_id = None
