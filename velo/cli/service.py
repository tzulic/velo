"""Service management for the Velo gateway daemon.

Handles systemd (Linux) and launchd (macOS) service installation,
lifecycle management, and status reporting. Adapted from Hermes' proven
production patterns for running AI agent gateways on VPS infrastructure.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

from loguru import logger

from velo.config.paths import get_velo_home

# ---------------------------------------------------------------------------
# Platform detection
# ---------------------------------------------------------------------------

_SERVICE_BASE = "velo-gateway"
_SERVICE_DESCRIPTION = "Velo AI Assistant Gateway"
_LAUNCHD_LABEL = "ai.velo.gateway"


def is_linux() -> bool:
    return sys.platform.startswith("linux")


def is_macos() -> bool:
    return sys.platform == "darwin"


# ---------------------------------------------------------------------------
# Common helpers
# ---------------------------------------------------------------------------


def get_pid_file() -> Path:
    """Return the gateway PID file path.

    Returns:
        Path: Path to gateway.pid within Velo home.
    """
    return get_velo_home() / "gateway.pid"


def get_running_pid() -> int | None:
    """Read the gateway PID file and check if the process is alive.

    Returns:
        int | None: PID if process is running, None otherwise.
    """
    pid_file = get_pid_file()
    if not pid_file.exists():
        return None

    try:
        pid = int(pid_file.read_text().strip())
        os.kill(pid, 0)  # Check if process exists
        return pid
    except (ValueError, ProcessLookupError, PermissionError):
        # Stale PID file — clean up
        pid_file.unlink(missing_ok=True)
        return None


def write_pid_file() -> None:
    pid_file = get_pid_file()
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    pid_file.write_text(str(os.getpid()))


def remove_pid_file() -> None:
    get_pid_file().unlink(missing_ok=True)


def get_service_name() -> str:
    """Derive a service name scoped to this VELO_HOME.

    Default ~/.velo returns 'velo-gateway'. Any other VELO_HOME appends
    a short hash so multiple installations don't conflict.

    Returns:
        str: Systemd/launchd service identifier.
    """
    home = get_velo_home()
    default = (Path.home() / ".velo").resolve()
    if home == default:
        return _SERVICE_BASE
    suffix = hashlib.sha256(str(home).encode()).hexdigest()[:8]
    return f"{_SERVICE_BASE}-{suffix}"


def _get_python_path() -> str:
    """Return the Python executable path, preferring virtualenv.

    Returns:
        str: Path to the python binary.
    """
    # Check for virtualenv
    venv = os.environ.get("VIRTUAL_ENV")
    if venv:
        venv_python = Path(venv) / "bin" / "python"
        if venv_python.exists():
            return str(venv_python)
    return sys.executable


def _get_velo_bin() -> str:
    """Return the path to the velo CLI binary.

    Returns:
        str: Path to velo executable or module invocation.
    """
    velo_bin = shutil.which("velo")
    if velo_bin:
        return velo_bin
    return f"{_get_python_path()} -m velo.cli.commands"


def _normalize_definition(text: str) -> str:
    """Normalize service definition for comparison.

    Args:
        text: Raw service definition text.

    Returns:
        str: Normalized text with trailing whitespace stripped.
    """
    return "\n".join(line.rstrip() for line in text.strip().splitlines())


# ---------------------------------------------------------------------------
# Systemd (Linux)
# ---------------------------------------------------------------------------


def get_systemd_unit_path(system: bool = False) -> Path:
    """Return the systemd unit file path.

    Args:
        system: If True, return system-level path. Otherwise user-level.

    Returns:
        Path: Path to the .service unit file.
    """
    name = get_service_name()
    if system:
        return Path("/etc/systemd/system") / f"{name}.service"
    return Path.home() / ".config" / "systemd" / "user" / f"{name}.service"


def generate_systemd_unit(system: bool = False, run_as_user: str | None = None) -> str:
    """Generate a systemd unit file for the Velo gateway.

    Args:
        system: If True, generate a system-level unit with User/Group.
        run_as_user: Username for system-level service.

    Returns:
        str: Complete systemd unit file content.
    """
    velo_bin = _get_velo_bin()
    velo_home = str(get_velo_home())

    # Build PATH with virtualenv bin if present
    path_entries: list[str] = []
    venv = os.environ.get("VIRTUAL_ENV")
    if venv:
        path_entries.append(str(Path(venv) / "bin"))
    path_entries.extend(["/usr/local/bin", "/usr/bin", "/bin"])
    sane_path = ":".join(path_entries)

    exec_start = f"{velo_bin} gateway"
    if " -m " in velo_bin:
        # Module invocation needs full path
        exec_start = velo_bin.replace("-m velo.cli.commands", "-m velo.cli.commands gateway")

    common_section = """\
Restart=on-failure
RestartSec=30
KillMode=mixed
KillSignal=SIGTERM
TimeoutStopSec=60
StandardOutput=journal
StandardError=journal"""

    if system and run_as_user:
        import grp
        import pwd

        user_info = pwd.getpwnam(run_as_user)
        group_name = grp.getgrgid(user_info.pw_gid).gr_name

        return f"""\
[Unit]
Description={_SERVICE_DESCRIPTION}
After=network-online.target
Wants=network-online.target
StartLimitIntervalSec=600
StartLimitBurst=5

[Service]
Type=simple
User={run_as_user}
Group={group_name}
ExecStart={exec_start}
Environment="HOME={user_info.pw_dir}"
Environment="PATH={sane_path}"
Environment="VELO_HOME={velo_home}"
{common_section}

[Install]
WantedBy=multi-user.target
"""

    return f"""\
[Unit]
Description={_SERVICE_DESCRIPTION}
After=network.target
StartLimitIntervalSec=600
StartLimitBurst=5

[Service]
Type=simple
ExecStart={exec_start}
Environment="PATH={sane_path}"
Environment="VELO_HOME={velo_home}"
{common_section}

[Install]
WantedBy=default.target
"""


def _ensure_user_systemd_env() -> None:
    """Ensure DBUS_SESSION_BUS_ADDRESS is set for systemctl --user on headless servers."""
    uid = os.getuid()
    if "XDG_RUNTIME_DIR" not in os.environ:
        runtime_dir = f"/run/user/{uid}"
        if Path(runtime_dir).exists():
            os.environ["XDG_RUNTIME_DIR"] = runtime_dir
    if "DBUS_SESSION_BUS_ADDRESS" not in os.environ:
        xdg_runtime = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{uid}")
        bus_path = Path(xdg_runtime) / "bus"
        if bus_path.exists():
            os.environ["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={bus_path}"


def _systemctl(system: bool = False) -> list[str]:
    """Return the base systemctl command.

    Args:
        system: If True, return system-level command.

    Returns:
        list[str]: systemctl command parts.
    """
    if not system:
        _ensure_user_systemd_env()
    return ["systemctl"] if system else ["systemctl", "--user"]


def systemd_unit_is_current(system: bool = False) -> bool:
    """Check if the installed unit matches the currently generated one.

    Args:
        system: Check system-level unit.

    Returns:
        bool: True if definitions match.
    """
    unit_path = get_systemd_unit_path(system=system)
    if not unit_path.exists():
        return False
    installed = unit_path.read_text(encoding="utf-8")
    expected = generate_systemd_unit(system=system)
    return _normalize_definition(installed) == _normalize_definition(expected)


def systemd_install(force: bool = False, system: bool = False) -> None:
    """Install the systemd service unit.

    Args:
        force: Reinstall even if already present.
        system: Install as system service (requires root).
    """
    if system and os.geteuid() != 0:
        print("System service install requires root. Re-run with sudo.")
        sys.exit(1)

    unit_path = get_systemd_unit_path(system=system)

    if unit_path.exists() and not force:
        if not systemd_unit_is_current(system=system):
            print(f"Repairing outdated service at: {unit_path}")
            unit_path.write_text(generate_systemd_unit(system=system), encoding="utf-8")
            subprocess.run(_systemctl(system) + ["daemon-reload"], check=True)
            subprocess.run(_systemctl(system) + ["enable", get_service_name()], check=True)
            print("Service definition updated.")
            return
        print(f"Service already installed at: {unit_path}")
        print("Use --force to reinstall.")
        return

    unit_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"Installing service to: {unit_path}")
    unit_path.write_text(generate_systemd_unit(system=system), encoding="utf-8")
    subprocess.run(_systemctl(system) + ["daemon-reload"], check=True)
    subprocess.run(_systemctl(system) + ["enable", get_service_name()], check=True)

    scope = "system" if system else "user"
    print(f"\nService installed and enabled ({scope})!")
    print("\nNext steps:")
    print("  velo service start    # Start the gateway")
    print("  velo service status   # Check status")

    if not system:
        _check_linger()


def systemd_uninstall(system: bool = False) -> None:
    """Remove the systemd service unit.

    Args:
        system: Remove system-level service.
    """
    name = get_service_name()
    subprocess.run(_systemctl(system) + ["stop", name], check=False)
    subprocess.run(_systemctl(system) + ["disable", name], check=False)

    unit_path = get_systemd_unit_path(system=system)
    if unit_path.exists():
        unit_path.unlink()
        print(f"Removed {unit_path}")

    subprocess.run(_systemctl(system) + ["daemon-reload"], check=True)
    print("Service uninstalled.")


def _refresh_systemd_if_stale(system: bool = False) -> None:
    """Rewrite and reload the systemd unit if it differs from the generated one."""
    unit_path = get_systemd_unit_path(system=system)
    if unit_path.exists() and not systemd_unit_is_current(system=system):
        unit_path.write_text(generate_systemd_unit(system=system), encoding="utf-8")
        subprocess.run(_systemctl(system) + ["daemon-reload"], check=True)
        print("Updated stale service definition.")


def systemd_start(system: bool = False) -> None:
    """Start the systemd service.

    Args:
        system: Start system-level service.
    """
    _refresh_systemd_if_stale(system)

    subprocess.run(_systemctl(system) + ["start", get_service_name()], check=True)
    print("Service started.")


def systemd_stop(system: bool = False) -> None:
    """Stop the systemd service.

    Args:
        system: Stop system-level service.
    """
    subprocess.run(_systemctl(system) + ["stop", get_service_name()], check=True)
    print("Service stopped.")


def systemd_restart(system: bool = False) -> None:
    """Restart the systemd service.

    Args:
        system: Restart system-level service.
    """
    _refresh_systemd_if_stale(system)

    subprocess.run(_systemctl(system) + ["restart", get_service_name()], check=True)
    print("Service restarted.")


def systemd_status(system: bool = False) -> None:
    """Show systemd service status.

    Args:
        system: Show system-level service status.
    """
    unit_path = get_systemd_unit_path(system=system)
    if not unit_path.exists():
        print("Service is not installed.")
        print("  Run: velo service install")
        return

    if not systemd_unit_is_current(system=system):
        print("Warning: service definition is outdated.")
        print("  Run: velo service restart  (auto-refreshes)")
        print()

    subprocess.run(
        _systemctl(system) + ["status", get_service_name(), "--no-pager"],
        capture_output=False,
    )

    result = subprocess.run(
        _systemctl(system) + ["is-active", get_service_name()],
        capture_output=True,
        text=True,
    )
    status = result.stdout.strip()
    if status == "active":
        print("\nGateway is running.")
    else:
        print("\nGateway is stopped.")
        print("  Run: velo service start")

    if not system:
        _check_linger()


def _check_linger() -> None:
    """Check and report systemd linger status for headless servers."""
    if not is_linux():
        return

    if not shutil.which("loginctl"):
        return

    username = os.getenv("USER") or os.getenv("LOGNAME")
    if not username:
        return

    try:
        result = subprocess.run(
            ["loginctl", "show-user", username, "--property=Linger", "--value"],
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception:
        return

    value = (result.stdout or "").strip().lower()
    if value in {"yes", "true", "1"}:
        print("Linger is enabled (service survives logout).")
    elif value in {"no", "false", "0"}:
        print("\nWarning: linger is disabled — gateway may stop when you log out.")
        print(f"  Run: sudo loginctl enable-linger {username}")


# ---------------------------------------------------------------------------
# Launchd (macOS)
# ---------------------------------------------------------------------------


def get_launchd_plist_path() -> Path:
    """Return the launchd plist file path.

    Returns:
        Path: Path to the .plist file in ~/Library/LaunchAgents.
    """
    return Path.home() / "Library" / "LaunchAgents" / f"{_LAUNCHD_LABEL}.plist"


def generate_launchd_plist() -> str:
    """Generate a launchd plist for the Velo gateway.

    Returns:
        str: Complete plist XML content.
    """
    velo_bin = _get_velo_bin()
    log_dir = get_velo_home() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    # Build program arguments
    if " -m " in velo_bin:
        python_path, _, module = velo_bin.partition(" -m ")
        args = f"""\
        <string>{python_path.strip()}</string>
        <string>-m</string>
        <string>{module.strip()}</string>
        <string>gateway</string>"""
    else:
        args = f"""\
        <string>{velo_bin}</string>
        <string>gateway</string>"""

    return f"""\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" \
"http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{_LAUNCHD_LABEL}</string>

    <key>ProgramArguments</key>
    <array>
{args}
    </array>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <dict>
        <key>SuccessfulExit</key>
        <false/>
    </dict>

    <key>StandardOutPath</key>
    <string>{log_dir}/gateway.log</string>

    <key>StandardErrorPath</key>
    <string>{log_dir}/gateway.error.log</string>
</dict>
</plist>
"""


def launchd_plist_is_current() -> bool:
    """Check if the installed plist matches the generated one.

    Returns:
        bool: True if definitions match.
    """
    plist_path = get_launchd_plist_path()
    if not plist_path.exists():
        return False
    installed = plist_path.read_text(encoding="utf-8")
    expected = generate_launchd_plist()
    return _normalize_definition(installed) == _normalize_definition(expected)


def launchd_install(force: bool = False) -> None:
    """Install the launchd service.

    Args:
        force: Reinstall even if already present.
    """
    plist_path = get_launchd_plist_path()

    if plist_path.exists() and not force:
        if not launchd_plist_is_current():
            print(f"Repairing outdated service at: {plist_path}")
            subprocess.run(["launchctl", "unload", str(plist_path)], check=False)
            plist_path.write_text(generate_launchd_plist(), encoding="utf-8")
            subprocess.run(["launchctl", "load", str(plist_path)], check=False)
            print("Service definition updated.")
            return
        print(f"Service already installed at: {plist_path}")
        print("Use --force to reinstall.")
        return

    plist_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"Installing service to: {plist_path}")
    plist_path.write_text(generate_launchd_plist(), encoding="utf-8")
    subprocess.run(["launchctl", "load", str(plist_path)], check=True)

    print("\nService installed and loaded!")
    print("\nNext steps:")
    print("  velo service status                         # Check status")
    print(f"  tail -f {get_velo_home()}/logs/gateway.log  # View logs")


def launchd_uninstall() -> None:
    """Remove the launchd service."""
    plist_path = get_launchd_plist_path()
    subprocess.run(["launchctl", "unload", str(plist_path)], check=False)
    if plist_path.exists():
        plist_path.unlink()
        print(f"Removed {plist_path}")
    print("Service uninstalled.")


def launchd_start() -> None:
    """Start the launchd service."""
    plist_path = get_launchd_plist_path()

    # Auto-refresh stale definitions
    if plist_path.exists() and not launchd_plist_is_current():
        subprocess.run(["launchctl", "unload", str(plist_path)], check=False)
        plist_path.write_text(generate_launchd_plist(), encoding="utf-8")
        subprocess.run(["launchctl", "load", str(plist_path)], check=False)
        print("Updated stale service definition.")

    try:
        subprocess.run(["launchctl", "start", _LAUNCHD_LABEL], check=True)
    except subprocess.CalledProcessError as e:
        if e.returncode != 3 or not plist_path.exists():
            raise
        print("Reloading service definition...")
        subprocess.run(["launchctl", "load", str(plist_path)], check=True)
        subprocess.run(["launchctl", "start", _LAUNCHD_LABEL], check=True)
    print("Service started.")


def launchd_stop() -> None:
    """Stop the launchd service."""
    subprocess.run(["launchctl", "stop", _LAUNCHD_LABEL], check=True)
    print("Service stopped.")


def launchd_restart() -> None:
    """Restart the launchd service."""
    try:
        launchd_stop()
    except subprocess.CalledProcessError as e:
        if e.returncode != 3:
            raise
        print("Service was not loaded; skipping stop.")

    _wait_for_exit()
    launchd_start()


def launchd_status() -> None:
    """Show launchd service status."""
    plist_path = get_launchd_plist_path()

    if not plist_path.exists():
        print("Service is not installed.")
        print("  Run: velo service install")
        return

    if not launchd_plist_is_current():
        print("Warning: service definition is outdated.")
        print("  Run: velo service start  (auto-refreshes)")
        print()

    result = subprocess.run(
        ["launchctl", "list", _LAUNCHD_LABEL],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        print("Gateway is loaded.")
        print(result.stdout)
    else:
        print("Gateway is not loaded.")
        print("  Run: velo service start")

    log_file = get_velo_home() / "logs" / "gateway.log"
    if log_file.exists():
        print("\nRecent logs:")
        subprocess.run(["tail", "-10", str(log_file)])


# ---------------------------------------------------------------------------
# Shared lifecycle helpers
# ---------------------------------------------------------------------------


def _wait_for_exit(timeout: float = 10.0, force_after: float = 5.0) -> None:
    """Wait for the gateway process to exit using the PID file.

    Args:
        timeout: Total seconds to wait before giving up.
        force_after: Seconds of graceful waiting before sending SIGKILL.
    """
    deadline = time.monotonic() + timeout
    force_deadline = time.monotonic() + force_after
    force_sent = False

    while time.monotonic() < deadline:
        pid = get_running_pid()
        if pid is None:
            return

        if not force_sent and time.monotonic() >= force_deadline:
            try:
                os.kill(pid, signal.SIGKILL)
                logger.warning("Gateway PID {} did not exit gracefully; sent SIGKILL", pid)
            except (ProcessLookupError, PermissionError):
                return
            force_sent = True

        time.sleep(0.3)

    remaining = get_running_pid()
    if remaining is not None:
        logger.warning("Gateway PID {} still running after {}s", remaining, timeout)


# ---------------------------------------------------------------------------
# Dispatch: auto-detect platform
# ---------------------------------------------------------------------------


def service_install(force: bool = False, system: bool = False) -> None:
    """Install the gateway service for the current platform.

    Args:
        force: Reinstall even if present.
        system: Linux only — install as system service.
    """
    if is_linux():
        systemd_install(force=force, system=system)
    elif is_macos():
        launchd_install(force=force)
    else:
        print(f"Service management not supported on {sys.platform}.")
        print("Run 'velo gateway' directly or use Docker.")


def service_uninstall(system: bool = False) -> None:
    """Uninstall the gateway service.

    Args:
        system: Linux only — remove system service.
    """
    if is_linux():
        systemd_uninstall(system=system)
    elif is_macos():
        launchd_uninstall()
    else:
        print(f"Not supported on {sys.platform}.")


def service_start(system: bool = False) -> None:
    """Start the gateway service.

    Args:
        system: Linux only — start system service.
    """
    if is_linux():
        systemd_start(system=system)
    elif is_macos():
        launchd_start()
    else:
        print(f"Not supported on {sys.platform}. Run 'velo gateway' directly.")


def service_stop(system: bool = False) -> None:
    """Stop the gateway service.

    Args:
        system: Linux only — stop system service.
    """
    if is_linux():
        systemd_stop(system=system)
    elif is_macos():
        launchd_stop()
    else:
        print(f"Not supported on {sys.platform}.")


def service_restart(system: bool = False) -> None:
    """Restart the gateway service.

    Args:
        system: Linux only — restart system service.
    """
    if is_linux():
        systemd_restart(system=system)
    elif is_macos():
        launchd_restart()
    else:
        print(f"Not supported on {sys.platform}.")


def service_status(system: bool = False) -> None:
    """Show gateway service status.

    Args:
        system: Linux only — show system service status.
    """
    if is_linux():
        systemd_status(system=system)
    elif is_macos():
        launchd_status()
    else:
        pid = get_running_pid()
        if pid:
            print(f"Gateway is running (PID {pid}).")
        else:
            print("Gateway is not running.")
