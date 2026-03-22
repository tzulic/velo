"""CLI commands for velo."""

from __future__ import annotations

import asyncio
import os
import select
import signal
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from velo.agent.loop import AgentLoop
    from velo.bus.queue import MessageBus
    from velo.plugins.manager import PluginManager
    from velo.providers.base import LLMProvider

# Force UTF-8 encoding for Windows console
if sys.platform == "win32":
    if sys.stdout.encoding != "utf-8":
        os.environ["PYTHONIOENCODING"] = "utf-8"
        # Re-open stdout/stderr with UTF-8 encoding
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

import typer
from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.history import FileHistory
from prompt_toolkit.patch_stdout import patch_stdout
from rich.console import Console
from rich.markdown import Markdown
from rich.table import Table
from rich.text import Text

from velo import __logo__, __version__
from velo.config.paths import get_workspace_path
from velo.config.schema import Config
from velo.utils.helpers import sync_workspace_templates

app = typer.Typer(
    name="velo",
    help=f"{__logo__} Velo - Personal AI Assistant",
    no_args_is_help=True,
)

console = Console()
EXIT_COMMANDS = {"exit", "quit", "/exit", "/quit", ":q"}

# ---------------------------------------------------------------------------
# CLI input: prompt_toolkit for editing, paste, history, and display
# ---------------------------------------------------------------------------

_PROMPT_SESSION: PromptSession | None = None
_SAVED_TERM_ATTRS = None  # original termios settings, restored on exit


def _flush_pending_tty_input() -> None:
    """Drop unread keypresses typed while the model was generating output."""
    try:
        fd = sys.stdin.fileno()
        if not os.isatty(fd):
            return
    except Exception:
        return

    try:
        import termios

        termios.tcflush(fd, termios.TCIFLUSH)
        return
    except Exception:
        pass

    try:
        while True:
            ready, _, _ = select.select([fd], [], [], 0)
            if not ready:
                break
            if not os.read(fd, 4096):
                break
    except Exception:
        return


def _restore_terminal() -> None:
    """Restore terminal to its original state (echo, line buffering, etc.)."""
    if _SAVED_TERM_ATTRS is None:
        return
    try:
        import termios

        termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, _SAVED_TERM_ATTRS)
    except Exception:
        pass


def _init_prompt_session() -> None:
    """Create the prompt_toolkit session with persistent file history."""
    global _PROMPT_SESSION, _SAVED_TERM_ATTRS

    # Save terminal state so we can restore it on exit
    try:
        import termios

        _SAVED_TERM_ATTRS = termios.tcgetattr(sys.stdin.fileno())
    except Exception:
        pass

    from velo.config.paths import get_cli_history_path

    history_file = get_cli_history_path()
    history_file.parent.mkdir(parents=True, exist_ok=True)

    _PROMPT_SESSION = PromptSession(
        history=FileHistory(str(history_file)),
        enable_open_in_editor=False,
        multiline=False,  # Enter submits (single line mode)
    )


def _print_agent_response(response: str, render_markdown: bool) -> None:
    """Render assistant response with consistent terminal styling."""
    content = response or ""
    body = Markdown(content) if render_markdown else Text(content)
    console.print()
    console.print(f"[cyan]{__logo__} Velo[/cyan]")
    console.print(body)
    console.print()


def _is_exit_command(command: str) -> bool:
    """Return True when input should end interactive chat."""
    return command.lower() in EXIT_COMMANDS


async def _read_interactive_input_async() -> str:
    """Read user input using prompt_toolkit (handles paste, history, display).

    prompt_toolkit natively handles:
    - Multiline paste (bracketed paste mode)
    - History navigation (up/down arrows)
    - Clean display (no ghost characters or artifacts)
    """
    if _PROMPT_SESSION is None:
        raise RuntimeError("Call _init_prompt_session() first")
    try:
        with patch_stdout():
            return await _PROMPT_SESSION.prompt_async(
                HTML("<b fg='ansiblue'>You:</b> "),
            )
    except EOFError as exc:
        raise KeyboardInterrupt from exc


def version_callback(value: bool):
    if value:
        console.print(f"{__logo__} Velo v{__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(None, "--version", "-v", callback=version_callback, is_eager=True),
):
    """Velo - Personal AI Assistant."""
    pass


# ============================================================================
# Onboard / Setup
# ============================================================================


@app.command()
def onboard():
    """Initialize Velo configuration and workspace."""
    from velo.config.loader import get_config_path, load_config, save_config
    from velo.config.schema import Config

    config_path = get_config_path()

    if config_path.exists():
        console.print(f"[yellow]Config already exists at {config_path}[/yellow]")
        console.print("  [bold]y[/bold] = overwrite with defaults (existing values will be lost)")
        console.print(
            "  [bold]N[/bold] = refresh config, keeping existing values and adding new fields"
        )
        if typer.confirm("Overwrite?"):
            config = Config()
            save_config(config)
            console.print(f"[green]✓[/green] Config reset to defaults at {config_path}")
        else:
            config = load_config()
            save_config(config)
            console.print(
                f"[green]✓[/green] Config refreshed at {config_path} (existing values preserved)"
            )
    else:
        save_config(Config())
        console.print(f"[green]✓[/green] Created config at {config_path}")

    # Create workspace
    workspace = get_workspace_path()

    if not workspace.exists():
        workspace.mkdir(parents=True, exist_ok=True)
        console.print(f"[green]✓[/green] Created workspace at {workspace}")

    sync_workspace_templates(workspace)

    console.print(f"\n{__logo__} Velo is ready!")
    console.print("\nNext steps:")
    console.print("  1. Add your API key to [cyan]~/.velo/config.json[/cyan]")
    console.print("     Get one at: https://openrouter.ai/keys")
    console.print('  2. Chat: [cyan]Velo agent -m "Hello!"[/cyan]')

    try:
        if sys.stdin.isatty() and typer.confirm(
            "\nSet up a messaging platform now?", default=False
        ):
            from velo.cli.platform_setup import run_platform_setup

            run_platform_setup(config_path)
    except (EOFError, KeyboardInterrupt):
        pass


def _build_fallback_provider(config: Config):
    """Build the fallback LLM provider if fallback_model is configured.

    Args:
        config (Config): Loaded configuration.

    Returns:
        LLMProvider | None: Fallback provider, or None if not configured or build fails.
    """
    if not config.agents.defaults.fallback_model:
        return None
    try:
        return _make_provider(config, config.agents.defaults.fallback_model)
    except SystemExit:
        console.print(
            "[yellow]Warning: Could not create fallback provider, continuing without.[/yellow]"
        )
        return None


def _make_provider(config: Config, model: str | None = None):
    """Create the appropriate LLM provider from config.

    Dispatches by ``provider_type`` from the registry to the correct native SDK
    provider class. Special cases: OpenAI Codex (OAuth), Claude CLI, Azure OpenAI.

    Args:
        config (Config): Loaded configuration.
        model (str | None): Override model name; defaults to config.agents.defaults.model.

    Returns:
        LLMProvider: Configured provider instance.
    """
    from velo.providers.registry import find_by_name

    model = model or config.agents.defaults.model
    provider_name = config.get_provider_name(model)
    p = config.get_provider(model)

    # --- Special-cased providers (non-standard auth or SDK) ----------------

    # OpenAI Codex (OAuth)
    if provider_name == "openai_codex" or model.startswith("openai-codex/"):
        from velo.providers.openai_codex_provider import OpenAICodexProvider

        return OpenAICodexProvider(default_model=model)

    # Claude CLI: invokes the claude binary directly via Claude Max subscription
    if provider_name == "claude_cli":
        from velo.providers.cli_provider import CliProvider

        cli_cfg = config.providers.claude_cli
        return CliProvider(
            model=cli_cfg.model,
            timeout_s=cli_cfg.timeout_s,
            permission_mode=cli_cfg.permission_mode,
            cli_path=cli_cfg.cli_path,
        )

    # Azure OpenAI: direct Azure endpoint with deployment name
    if provider_name == "azure_openai":
        from velo.providers.azure_openai_provider import AzureOpenAIProvider

        if not p or not p.api_key or not p.api_base:
            console.print("[red]Error: Azure OpenAI requires api_key and api_base.[/red]")
            console.print("Set them in ~/.velo/config.json under providers.azure_openai section")
            console.print("Use the model field to specify the deployment name.")
            raise typer.Exit(1)
        return AzureOpenAIProvider(
            api_key=p.api_key,
            api_base=p.api_base,
            default_model=model,
        )

    # --- Standard providers: dispatch by provider_type ---------------------

    spec = find_by_name(provider_name) if provider_name else None
    if not (p and p.api_key) and not (spec and spec.is_oauth):
        console.print("[red]Error: No API key configured.[/red]")
        console.print("Set one in ~/.velo/config.json under providers section")
        raise typer.Exit(1)

    api_key = p.api_key if p else ""
    api_base = config.get_api_base(model)
    extra_headers = p.extra_headers if p else None
    provider_type = spec.provider_type if spec else "openai"

    if provider_type == "anthropic":
        from velo.providers.anthropic_provider import AnthropicProvider

        return AnthropicProvider(
            api_key=api_key,
            api_base=api_base,
            default_model=model,
        )

    if provider_type == "mistral":
        from velo.providers.mistral_provider import MistralProvider

        return MistralProvider(
            api_key=api_key,
            api_base=api_base,
            default_model=model,
        )

    if provider_type == "gemini":
        from velo.providers.gemini_provider import GeminiProvider

        return GeminiProvider(
            api_key=api_key,
            api_base=api_base,
            default_model=model,
        )

    # Default: OpenAI-compatible (openai, deepseek, groq, xai, openrouter, custom, etc.)
    from velo.providers.openai_provider import OpenAIProvider

    return OpenAIProvider(
        api_key=api_key,
        api_base=api_base,
        default_model=model,
        extra_headers=extra_headers,
        backend=provider_name or "openai",
    )


def _load_runtime_config(config: str | None = None, workspace: str | None = None) -> Config:
    """Load config and optionally override the active workspace."""
    from velo.config.loader import load_config, set_config_path

    config_path = None
    if config:
        config_path = Path(config).expanduser().resolve()
        if not config_path.exists():
            console.print(f"[red]Error: Config file not found: {config_path}[/red]")
            raise typer.Exit(1)
        set_config_path(config_path)
        console.print(f"[dim]Using config: {config_path}[/dim]")

    loaded = load_config(config_path)
    if workspace:
        loaded.agents.defaults.workspace = workspace
    return loaded


# ============================================================================
# Plugin lifecycle helper
# ============================================================================


async def _activate_plugins(
    plugin_mgr: "PluginManager",
    agent_loop: "AgentLoop",
    provider: "LLMProvider",
    bus: "MessageBus",
) -> None:
    """Load plugins, inject runtime refs, register tools, and start services.

    Args:
        plugin_mgr: PluginManager instance.
        agent_loop: AgentLoop instance.
        provider: LLM provider.
        bus: MessageBus instance.
    """
    from velo.plugins.types import RuntimeRefs

    await plugin_mgr.load_all()
    plugin_mgr.set_runtime(
        RuntimeRefs(
            provider=provider,
            model=agent_loop.model,
            bus=bus,
            process_direct=agent_loop.process_direct,
            publish_outbound=bus.publish_outbound,
            session_manager=agent_loop.sessions,
        )
    )
    agent_loop._register_plugin_tools()
    await plugin_mgr.start_services()


# ============================================================================
# Gateway / Server
# ============================================================================


@app.command()
def gateway(
    port: int = typer.Option(18790, "--port", "-p", help="Gateway port"),
    workspace: str | None = typer.Option(None, "--workspace", "-w", help="Workspace directory"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
    config: str | None = typer.Option(None, "--config", "-c", help="Path to config file"),
):
    """Start the Velo gateway."""
    from velo.agent.factory import build_agent_loop
    from velo.bus.queue import MessageBus
    from velo.channels.manager import ChannelManager
    from velo.config.paths import get_cron_dir
    from velo.cron.service import CronService
    from velo.cron.types import CronJob
    from velo.heartbeat.service import HeartbeatService
    from velo.session.manager import SessionManager

    if verbose:
        import logging

        logging.basicConfig(level=logging.DEBUG)

    config = _load_runtime_config(config, workspace)

    console.print(f"{__logo__} Starting Velo gateway on port {port}...")
    sync_workspace_templates(config.workspace_path)

    from velo.plugins.manager import PluginManager

    plugin_mgr = PluginManager(workspace=config.workspace_path, config=config.plugins)

    bus = MessageBus()
    provider = _make_provider(config)
    session_manager = SessionManager(
        config.workspace_path, backend=config.agents.defaults.session_backend
    )
    fallback_provider = _build_fallback_provider(config)

    # Create cron service first (callback set after agent creation)
    cron_store_path = get_cron_dir() / "jobs.json"
    cron = CronService(cron_store_path)

    # Create agent with cron service and plugin manager
    agent = build_agent_loop(
        config=config,
        bus=bus,
        provider=provider,
        cron_service=cron,
        plugin_manager=plugin_mgr,
        fallback_provider=fallback_provider,
        session_manager=session_manager,
    )

    # Set cron callback (needs agent)
    async def on_cron_job(job: CronJob) -> str | None:
        """Execute a cron job through the agent."""
        from velo.agent.tools.cron import CronTool
        from velo.agent.tools.message import MessageTool

        reminder_note = (
            "[Scheduled Task] Timer finished.\n\n"
            f"Task '{job.name}' has been triggered.\n"
            f"Scheduled instruction: {job.payload.message}"
        )

        # Prevent the agent from scheduling new cron jobs during execution
        cron_tool = agent.tools.get("cron")
        cron_token = None
        if isinstance(cron_tool, CronTool):
            cron_token = cron_tool.set_cron_context(True)
        try:
            response = await agent.process_direct(
                reminder_note,
                session_key=f"cron:{job.id}",
                channel=job.payload.channel or "cli",
                chat_id=job.payload.to or "direct",
            )
        finally:
            if isinstance(cron_tool, CronTool) and cron_token is not None:
                cron_tool.reset_cron_context(cron_token)

        message_tool = agent.tools.get("message")
        if isinstance(message_tool, MessageTool) and message_tool._sent_in_turn:
            return response

        if job.payload.deliver and job.payload.to and response:
            from velo.bus.events import OutboundMessage

            await bus.publish_outbound(
                OutboundMessage(
                    channel=job.payload.channel or "cli", chat_id=job.payload.to, content=response
                )
            )
        return response

    cron.on_job = on_cron_job

    # Create channel manager
    channels = ChannelManager(config, bus)

    def _pick_heartbeat_target() -> tuple[str, str]:
        """Pick a routable channel/chat target for heartbeat-triggered messages."""
        enabled = set(channels.enabled_channels)
        # Prefer the most recently updated non-internal session on an enabled channel.
        for item in session_manager.list_sessions():
            key = item.get("key") or ""
            if ":" not in key:
                continue
            channel, chat_id = key.split(":", 1)
            if channel in {"cli", "system"}:
                continue
            if channel in enabled and chat_id:
                return channel, chat_id
        # Fallback keeps prior behavior but remains explicit.
        return "cli", "direct"

    # Create heartbeat service
    async def on_heartbeat_execute(tasks: str) -> str:
        """Phase 2: execute heartbeat tasks through the full agent loop."""
        channel, chat_id = _pick_heartbeat_target()

        async def _silent(*_args, **_kwargs):
            pass

        return await agent.process_direct(
            tasks,
            session_key="heartbeat",
            channel=channel,
            chat_id=chat_id,
            on_progress=_silent,
        )

    async def on_heartbeat_notify(response: str) -> None:
        """Deliver a heartbeat response to the user's channel."""
        from velo.bus.events import OutboundMessage

        channel, chat_id = _pick_heartbeat_target()
        if channel == "cli":
            return  # No external channel available to deliver to
        await bus.publish_outbound(
            OutboundMessage(channel=channel, chat_id=chat_id, content=response)
        )

    hb_cfg = config.gateway.heartbeat
    heartbeat = HeartbeatService(
        workspace=config.workspace_path,
        provider=provider,
        model=agent.model,
        on_execute=on_heartbeat_execute,
        on_notify=on_heartbeat_notify,
        interval_s=hb_cfg.interval_s,
        enabled=hb_cfg.enabled,
        session_manager=session_manager,
    )

    if channels.enabled_channels:
        console.print(f"[green]✓[/green] Channels enabled: {', '.join(channels.enabled_channels)}")
    else:
        console.print("[yellow]Warning: No channels enabled[/yellow]")

    cron_status = cron.status()
    if cron_status["jobs"] > 0:
        console.print(f"[green]✓[/green] Cron: {cron_status['jobs']} scheduled jobs")

    console.print(f"[green]✓[/green] Heartbeat: every {hb_cfg.interval_s}s")

    async def run():
        # Start plugin HTTP server if routes are registered
        from velo.plugins.http import PluginHttpServer

        http_server: PluginHttpServer | None = None

        try:
            await _activate_plugins(plugin_mgr, agent, provider, bus)

            # Add plugin channels to channel manager
            plugin_channels = plugin_mgr.get_plugin_channels()
            if plugin_channels:
                channels.add_plugin_channels(plugin_channels)

            # Start plugin HTTP server if any routes were registered
            if plugin_mgr.http_routes:
                from velo.plugins.http import RouteTable

                route_table = RouteTable()
                for route in plugin_mgr.http_routes:
                    route_table.register(
                        method=route["method"],
                        path=route["path"],
                        handler=route["handler"],
                        plugin_name=route["plugin_name"],
                    )
                http_server = PluginHttpServer(route_table, port=port)
                await http_server.start()
                console.print(
                    f"[green]✓[/green] Plugin HTTP server: port {port} "
                    f"({len(plugin_mgr.http_routes)} route(s))"
                )

            await cron.start()
            await heartbeat.start()

            gather_tasks = [agent.run(), channels.start_all()]
            if config.a2a.enabled:
                from velo.a2a.server import start_a2a_server

                console.print(f"[green]✓[/green] A2A server: port {config.a2a.port}")
                gather_tasks.append(start_a2a_server(config.a2a, config.workspace_path, agent))

            await asyncio.gather(*gather_tasks)
        except KeyboardInterrupt:
            console.print("\nShutting down...")
        finally:
            if http_server:
                await http_server.stop()
            await plugin_mgr.shutdown()
            await agent.cleanup()
            heartbeat.stop()
            cron.stop()
            agent.stop()
            await channels.stop_all()

    asyncio.run(run())


# ============================================================================
# Agent Commands
# ============================================================================


@app.command()
def agent(
    message: str = typer.Option(None, "--message", "-m", help="Message to send to the agent"),
    session_id: str = typer.Option("cli:direct", "--session", "-s", help="Session ID"),
    workspace: str | None = typer.Option(None, "--workspace", "-w", help="Workspace directory"),
    config: str | None = typer.Option(None, "--config", "-c", help="Config file path"),
    markdown: bool = typer.Option(
        True, "--markdown/--no-markdown", help="Render assistant output as Markdown"
    ),
    logs: bool = typer.Option(False, "--logs/--no-logs", help="Show Velo runtime logs during chat"),
):
    """Interact with the agent directly."""
    from loguru import logger

    from velo.agent.factory import build_agent_loop
    from velo.bus.queue import MessageBus
    from velo.config.paths import get_cron_dir
    from velo.cron.service import CronService

    config = _load_runtime_config(config, workspace)
    sync_workspace_templates(config.workspace_path)

    from velo.plugins.manager import PluginManager

    plugin_mgr = PluginManager(workspace=config.workspace_path, config=config.plugins)

    bus = MessageBus()
    provider = _make_provider(config)

    fallback_provider = _build_fallback_provider(config)

    # Create cron service for tool usage (no callback needed for CLI unless running)
    cron_store_path = get_cron_dir() / "jobs.json"
    cron = CronService(cron_store_path)

    if logs:
        logger.enable("Velo")
    else:
        logger.disable("Velo")

    # Wire up clarify tool for interactive TTY sessions.
    async def _cli_clarify(question: str, choices: list[str] | None) -> str:
        """Present a clarifying question to the CLI user and return their answer."""
        if choices:
            opts = "\n".join(f"  {i + 1}. {c}" for i, c in enumerate(choices))
            prompt = f"\n❓ {question}\n{opts}\n  {len(choices) + 1}. Other\n> "
        else:
            prompt = f"\n❓ {question}\n> "
        return await asyncio.to_thread(input, prompt)

    # Only offer clarify on interactive TTY — headless/pipe runs skip it.
    is_interactive_tty = sys.stdin.isatty()
    clarify_callback = _cli_clarify if is_interactive_tty else None

    agent_loop = build_agent_loop(
        config=config,
        bus=bus,
        provider=provider,
        cron_service=cron,
        plugin_manager=plugin_mgr,
        fallback_provider=fallback_provider,
        clarify_callback=clarify_callback,
    )

    # Show spinner when logs are off (no output to miss); skip when logs are on
    def _thinking_ctx():
        if logs:
            from contextlib import nullcontext

            return nullcontext()
        # Animated spinner is safe to use with prompt_toolkit input handling
        return console.status("[dim]Velo is thinking...[/dim]", spinner="dots")

    async def _cli_progress(content: str, *, tool_hint: bool = False) -> None:
        ch = agent_loop.channels_config
        if ch and tool_hint and not ch.send_tool_hints:
            return
        if ch and not tool_hint and not ch.send_progress:
            return
        console.print(f"  [dim]↳ {content}[/dim]")

    if message:
        # Single message mode — direct call, no bus needed
        async def run_once():
            await _activate_plugins(plugin_mgr, agent_loop, provider, bus)
            try:
                with _thinking_ctx():
                    response = await agent_loop.process_direct(
                        message, session_id, on_progress=_cli_progress
                    )
                _print_agent_response(response, render_markdown=markdown)
            finally:
                await plugin_mgr.shutdown()
                await agent_loop.cleanup()

        asyncio.run(run_once())
    else:
        # Interactive mode — route through bus like other channels
        from velo.bus.events import InboundMessage

        _init_prompt_session()
        console.print(
            f"{__logo__} Interactive mode (type [bold]exit[/bold] or [bold]Ctrl+C[/bold] to quit)\n"
        )

        if ":" in session_id:
            cli_channel, cli_chat_id = session_id.split(":", 1)
        else:
            cli_channel, cli_chat_id = "cli", session_id

        def _handle_signal(signum, frame):
            sig_name = signal.Signals(signum).name
            _restore_terminal()
            console.print(f"\nReceived {sig_name}, goodbye!")
            sys.exit(0)

        signal.signal(signal.SIGINT, _handle_signal)
        signal.signal(signal.SIGTERM, _handle_signal)
        # SIGHUP is not available on Windows
        if hasattr(signal, "SIGHUP"):
            signal.signal(signal.SIGHUP, _handle_signal)
        # Ignore SIGPIPE to prevent silent process termination when writing to closed pipes
        # SIGPIPE is not available on Windows
        if hasattr(signal, "SIGPIPE"):
            signal.signal(signal.SIGPIPE, signal.SIG_IGN)

        async def run_interactive():
            await _activate_plugins(plugin_mgr, agent_loop, provider, bus)
            bus_task = asyncio.create_task(agent_loop.run())
            turn_done = asyncio.Event()
            turn_done.set()
            turn_response: list[str] = []

            async def _consume_outbound():
                while True:
                    try:
                        msg = await asyncio.wait_for(bus.consume_outbound(), timeout=1.0)
                        if msg.metadata.get("_progress"):
                            is_tool_hint = msg.metadata.get("_tool_hint", False)
                            ch = agent_loop.channels_config
                            if ch and is_tool_hint and not ch.send_tool_hints:
                                pass
                            elif ch and not is_tool_hint and not ch.send_progress:
                                pass
                            else:
                                console.print(f"  [dim]↳ {msg.content}[/dim]")
                        elif not turn_done.is_set():
                            if msg.content:
                                turn_response.append(msg.content)
                            turn_done.set()
                        elif msg.content:
                            console.print()
                            _print_agent_response(msg.content, render_markdown=markdown)
                    except TimeoutError:
                        continue
                    except asyncio.CancelledError:
                        break

            outbound_task = asyncio.create_task(_consume_outbound())

            try:
                while True:
                    try:
                        _flush_pending_tty_input()
                        user_input = await _read_interactive_input_async()
                        command = user_input.strip()
                        if not command:
                            continue

                        if _is_exit_command(command):
                            _restore_terminal()
                            console.print("\nGoodbye!")
                            break

                        turn_done.clear()
                        turn_response.clear()

                        await bus.publish_inbound(
                            InboundMessage(
                                channel=cli_channel,
                                sender_id="user",
                                chat_id=cli_chat_id,
                                content=user_input,
                            )
                        )

                        with _thinking_ctx():
                            await turn_done.wait()

                        if turn_response:
                            _print_agent_response(turn_response[0], render_markdown=markdown)
                    except KeyboardInterrupt:
                        _restore_terminal()
                        console.print("\nGoodbye!")
                        break
                    except EOFError:
                        _restore_terminal()
                        console.print("\nGoodbye!")
                        break
            finally:
                await plugin_mgr.shutdown()
                agent_loop.stop()
                outbound_task.cancel()
                await asyncio.gather(bus_task, outbound_task, return_exceptions=True)
                await agent_loop.cleanup()

        asyncio.run(run_interactive())


# ============================================================================
# Channel Commands
# ============================================================================


channels_app = typer.Typer(help="Manage channels")
app.add_typer(channels_app, name="channels")


@channels_app.command("setup")
def channels_setup_cmd():
    """Interactive setup wizard for messaging platforms."""
    from velo.cli.platform_setup import run_platform_setup
    from velo.config.loader import get_config_path

    run_platform_setup(get_config_path())


@channels_app.command("status")
def channels_status():
    """Show channel status."""
    from velo.config.loader import load_config

    config = load_config()

    table = Table(title="Channel Status")
    table.add_column("Channel", style="cyan")
    table.add_column("Enabled", style="green")
    table.add_column("Configuration", style="yellow")

    # WhatsApp
    wa = config.channels.whatsapp
    table.add_row("WhatsApp", "✓" if wa.enabled else "✗", wa.bridge_url)

    dc = config.channels.discord
    table.add_row("Discord", "✓" if dc.enabled else "✗", dc.gateway_url)

    # Feishu
    fs = config.channels.feishu
    fs_config = f"app_id: {fs.app_id[:10]}..." if fs.app_id else "[dim]not configured[/dim]"
    table.add_row("Feishu", "✓" if fs.enabled else "✗", fs_config)

    # Mochat
    mc = config.channels.mochat
    mc_base = mc.base_url or "[dim]not configured[/dim]"
    table.add_row("Mochat", "✓" if mc.enabled else "✗", mc_base)

    # Telegram
    tg = config.channels.telegram
    tg_config = f"token: {tg.token[:10]}..." if tg.token else "[dim]not configured[/dim]"
    table.add_row("Telegram", "✓" if tg.enabled else "✗", tg_config)

    # Slack
    slack = config.channels.slack
    slack_config = "socket" if slack.app_token and slack.bot_token else "[dim]not configured[/dim]"
    table.add_row("Slack", "✓" if slack.enabled else "✗", slack_config)

    # DingTalk
    dt = config.channels.dingtalk
    dt_config = (
        f"client_id: {dt.client_id[:10]}..." if dt.client_id else "[dim]not configured[/dim]"
    )
    table.add_row("DingTalk", "✓" if dt.enabled else "✗", dt_config)

    # QQ
    qq = config.channels.qq
    qq_config = f"app_id: {qq.app_id[:10]}..." if qq.app_id else "[dim]not configured[/dim]"
    table.add_row("QQ", "✓" if qq.enabled else "✗", qq_config)

    # Email
    em = config.channels.email
    em_config = em.imap_host if em.imap_host else "[dim]not configured[/dim]"
    table.add_row("Email", "✓" if em.enabled else "✗", em_config)

    console.print(table)


def _get_bridge_dir() -> Path:
    """Get the bridge directory, setting it up if needed."""
    import shutil
    import subprocess

    # User's bridge location
    from velo.config.paths import get_bridge_install_dir

    user_bridge = get_bridge_install_dir()

    # Check if already built
    if (user_bridge / "dist" / "index.js").exists():
        return user_bridge

    # Check for npm
    if not shutil.which("npm"):
        console.print("[red]npm not found. Please install Node.js >= 18.[/red]")
        raise typer.Exit(1)

    # Find source bridge: first check package data, then source dir
    pkg_bridge = Path(__file__).parent.parent / "bridge"  # Velo/bridge (installed)
    src_bridge = Path(__file__).parent.parent.parent / "bridge"  # repo root/bridge (dev)

    source = None
    if (pkg_bridge / "package.json").exists():
        source = pkg_bridge
    elif (src_bridge / "package.json").exists():
        source = src_bridge

    if not source:
        console.print("[red]Bridge source not found.[/red]")
        console.print("Try reinstalling: pip install --force-reinstall Velo")
        raise typer.Exit(1)

    console.print(f"{__logo__} Setting up bridge...")

    # Copy to user directory
    user_bridge.parent.mkdir(parents=True, exist_ok=True)
    if user_bridge.exists():
        shutil.rmtree(user_bridge)
    shutil.copytree(source, user_bridge, ignore=shutil.ignore_patterns("node_modules", "dist"))

    # Install and build
    try:
        console.print("  Installing dependencies...")
        subprocess.run(["npm", "install"], cwd=user_bridge, check=True, capture_output=True)

        console.print("  Building...")
        subprocess.run(["npm", "run", "build"], cwd=user_bridge, check=True, capture_output=True)

        console.print("[green]✓[/green] Bridge ready\n")
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Build failed: {e}[/red]")
        if e.stderr:
            console.print(f"[dim]{e.stderr.decode()[:500]}[/dim]")
        raise typer.Exit(1)

    return user_bridge


@channels_app.command("login")
def channels_login():
    """Link device via QR code."""
    import subprocess

    from velo.config.loader import load_config
    from velo.config.paths import get_runtime_subdir

    config = load_config()
    bridge_dir = _get_bridge_dir()

    console.print(f"{__logo__} Starting bridge...")
    console.print("Scan the QR code to connect.\n")

    env = {**os.environ}
    if config.channels.whatsapp.bridge_token:
        env["BRIDGE_TOKEN"] = config.channels.whatsapp.bridge_token
    env["AUTH_DIR"] = str(get_runtime_subdir("whatsapp-auth"))

    try:
        subprocess.run(["npm", "start"], cwd=bridge_dir, check=True, env=env)
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Bridge failed: {e}[/red]")
    except FileNotFoundError:
        console.print("[red]npm not found. Please install Node.js.[/red]")


# ============================================================================
# Status Commands
# ============================================================================


@app.command()
def status():
    """Show Velo status."""
    from velo.config.loader import get_config_path, load_config

    config_path = get_config_path()
    config = load_config()
    workspace = config.workspace_path

    console.print(f"{__logo__} Velo Status\n")

    console.print(
        f"Config: {config_path} {'[green]✓[/green]' if config_path.exists() else '[red]✗[/red]'}"
    )
    console.print(
        f"Workspace: {workspace} {'[green]✓[/green]' if workspace.exists() else '[red]✗[/red]'}"
    )

    if config_path.exists():
        from velo.providers.registry import PROVIDERS

        console.print(f"Model: {config.agents.defaults.model}")

        # Check API keys from registry
        for spec in PROVIDERS:
            p = getattr(config.providers, spec.name, None)
            if p is None:
                continue
            if spec.is_oauth:
                console.print(f"{spec.label}: [green]✓ (OAuth)[/green]")
            elif spec.is_local:
                # Local deployments show api_base instead of api_key
                if p.api_base:
                    console.print(f"{spec.label}: [green]✓ {p.api_base}[/green]")
                else:
                    console.print(f"{spec.label}: [dim]not set[/dim]")
            else:
                has_key = bool(p.api_key)
                console.print(
                    f"{spec.label}: {'[green]✓[/green]' if has_key else '[dim]not set[/dim]'}"
                )


# ============================================================================
# OAuth Login
# ============================================================================

provider_app = typer.Typer(help="Manage providers")
app.add_typer(provider_app, name="provider")


_LOGIN_HANDLERS: dict[str, callable] = {}


def _register_login(name: str):
    def decorator(fn):
        _LOGIN_HANDLERS[name] = fn
        return fn

    return decorator


@provider_app.command("login")
def provider_login(
    provider: str = typer.Argument(
        ..., help="OAuth provider (e.g. 'openai-codex', 'github-copilot')"
    ),
):
    """Authenticate with an OAuth provider."""
    from velo.providers.registry import PROVIDERS

    key = provider.replace("-", "_")
    spec = next((s for s in PROVIDERS if s.name == key and s.is_oauth), None)
    if not spec:
        names = ", ".join(s.name.replace("_", "-") for s in PROVIDERS if s.is_oauth)
        console.print(f"[red]Unknown OAuth provider: {provider}[/red]  Supported: {names}")
        raise typer.Exit(1)

    handler = _LOGIN_HANDLERS.get(spec.name)
    if not handler:
        console.print(f"[red]Login not implemented for {spec.label}[/red]")
        raise typer.Exit(1)

    console.print(f"{__logo__} OAuth Login - {spec.label}\n")
    handler()


@_register_login("openai_codex")
def _login_openai_codex() -> None:
    try:
        from oauth_cli_kit import get_token, login_oauth_interactive

        token = None
        try:
            token = get_token()
        except Exception:
            pass
        if not (token and token.access):
            console.print("[cyan]Starting interactive OAuth login...[/cyan]\n")
            token = login_oauth_interactive(
                print_fn=lambda s: console.print(s),
                prompt_fn=lambda s: typer.prompt(s),
            )
        if not (token and token.access):
            console.print("[red]✗ Authentication failed[/red]")
            raise typer.Exit(1)
        console.print(
            f"[green]✓ Authenticated with OpenAI Codex[/green]  [dim]{token.account_id}[/dim]"
        )
    except ImportError:
        console.print("[red]oauth_cli_kit not installed. Run: pip install oauth-cli-kit[/red]")
        raise typer.Exit(1)


@_register_login("github_copilot")
def _login_github_copilot() -> None:
    console.print("[yellow]GitHub Copilot login requires manual setup.[/yellow]")
    console.print(
        "Set your Copilot token in ~/.velo/config.json under providers.github_copilot.api_key"
    )
    console.print("See: https://github.com/settings/copilot for token management.")


# ============================================================================
# Service Commands (systemd/launchd management)
# ============================================================================

service_app = typer.Typer(help="Manage the gateway background service")
app.add_typer(service_app, name="service")


@service_app.command("install")
def service_install_cmd(
    force: bool = typer.Option(False, "--force", help="Reinstall even if present"),
    system: bool = typer.Option(False, "--system", help="Linux: install as system service"),
):
    """Install the gateway as a background service (systemd/launchd)."""
    from velo.cli.service import service_install

    service_install(force=force, system=system)


@service_app.command("uninstall")
def service_uninstall_cmd(
    system: bool = typer.Option(False, "--system", help="Linux: remove system service"),
):
    """Remove the gateway background service."""
    from velo.cli.service import service_uninstall

    service_uninstall(system=system)


@service_app.command("start")
def service_start_cmd(
    system: bool = typer.Option(False, "--system", help="Linux: start system service"),
):
    """Start the gateway background service."""
    from velo.cli.service import service_start

    service_start(system=system)


@service_app.command("stop")
def service_stop_cmd(
    system: bool = typer.Option(False, "--system", help="Linux: stop system service"),
):
    """Stop the gateway background service."""
    from velo.cli.service import service_stop

    service_stop(system=system)


@service_app.command("restart")
def service_restart_cmd(
    system: bool = typer.Option(False, "--system", help="Linux: restart system service"),
):
    """Restart the gateway background service."""
    from velo.cli.service import service_restart

    service_restart(system=system)


@service_app.command("status")
def service_status_cmd(
    system: bool = typer.Option(False, "--system", help="Linux: show system service"),
):
    """Show gateway service status."""
    from velo.cli.service import service_status

    service_status(system=system)


if __name__ == "__main__":
    app()
