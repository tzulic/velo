"""Platform setup wizard registry and interactive setup flow.

Each entry describes a chat platform that the onboarding wizard can configure.
The ``attr_path`` values map to Pydantic fields in ``velo.config.schema.ChannelsConfig``
so the wizard can write values into ``~/.velo/config.json`` at the correct location.

Functions:
    apply_platform_values: Write dot-path values into the Pydantic config model.
    run_platform_setup: Interactive CLI flow for selecting and configuring platforms.
"""

from __future__ import annotations

import getpass
from pathlib import Path
from typing import Any

from velo.config.loader import load_config, save_config

PlatformVar = dict[str, Any]
PlatformEntry = dict[str, Any]

PLATFORMS: list[PlatformEntry] = [
    # ── Telegram ──────────────────────────────────────────────
    {
        "key": "telegram",
        "label": "Telegram",
        "emoji": "\U0001f4e8",
        "setup_instructions": [
            "Open Telegram and search for @BotFather",
            "Send /newbot and follow the prompts to create a bot",
            "Copy the bot token (looks like 123456:ABC-DEF...)",
        ],
        "vars": [
            {
                "name": "Bot Token",
                "attr_path": "channels.telegram.token",
                "prompt": "Paste your Telegram bot token",
                "password": True,
                "is_allowlist": False,
                "help": "The token you received from @BotFather",
            },
            {
                "name": "Allowed Users",
                "attr_path": "channels.telegram.allow_from",
                "prompt": "Telegram user IDs or usernames to allow (comma-separated, leave empty for all)",
                "password": False,
                "is_allowlist": True,
                "help": "Restricts who can talk to the bot. Empty means everyone.",
            },
        ],
    },
    # ── Discord ───────────────────────────────────────────────
    {
        "key": "discord",
        "label": "Discord",
        "emoji": "\U0001f3ae",
        "setup_instructions": [
            "Go to https://discord.com/developers/applications",
            "Click 'New Application', give it a name, then go to the Bot tab",
            "Click 'Reset Token' and copy the bot token",
            "Under 'Privileged Gateway Intents', enable Message Content Intent",
            "Use the OAuth2 URL Generator to invite the bot to your server",
        ],
        "vars": [
            {
                "name": "Bot Token",
                "attr_path": "channels.discord.token",
                "prompt": "Paste your Discord bot token",
                "password": True,
                "is_allowlist": False,
                "help": "The token from the Bot tab in Discord Developer Portal",
            },
            {
                "name": "Allowed Users",
                "attr_path": "channels.discord.allow_from",
                "prompt": "Discord user IDs to allow (comma-separated, leave empty for all)",
                "password": False,
                "is_allowlist": True,
                "help": "Restricts who can talk to the bot. Empty means everyone.",
            },
        ],
    },
    # ── Slack ─────────────────────────────────────────────────
    {
        "key": "slack",
        "label": "Slack",
        "emoji": "\U0001f4ac",
        "setup_instructions": [
            "Go to https://api.slack.com/apps and click 'Create New App'",
            "Choose 'From scratch', name your app, and pick a workspace",
            "Go to 'OAuth & Permissions' and add bot scopes: chat:write, app_mentions:read, im:history, im:read",
            "Install the app to your workspace and copy the Bot Token (xoxb-...)",
            "Go to 'Socket Mode', enable it, and generate an App Token (xapp-...)",
        ],
        "vars": [
            {
                "name": "Bot Token",
                "attr_path": "channels.slack.bot_token",
                "prompt": "Paste your Slack bot token (xoxb-...)",
                "password": True,
                "is_allowlist": False,
                "help": "The Bot User OAuth Token from OAuth & Permissions",
            },
            {
                "name": "App Token",
                "attr_path": "channels.slack.app_token",
                "prompt": "Paste your Slack app token (xapp-...)",
                "password": True,
                "is_allowlist": False,
                "help": "The App-Level Token from Socket Mode settings",
            },
            {
                "name": "Allowed Users",
                "attr_path": "channels.slack.allow_from",
                "prompt": "Slack user IDs to allow (comma-separated, leave empty for all)",
                "password": False,
                "is_allowlist": True,
                "help": "Restricts who can talk to the bot. Empty means everyone.",
            },
        ],
    },
    # ── WhatsApp ──────────────────────────────────────────────
    {
        "key": "whatsapp",
        "label": "WhatsApp",
        "emoji": "\U0001f4f1",
        "setup_instructions": [
            "Velo uses a WhatsApp Web bridge (included in Docker image)",
            "Run 'docker compose up -d velo-bridge' to start the bridge",
            "Scan the QR code with WhatsApp on your phone to link the session",
            "The bridge token secures communication between Velo and the bridge",
        ],
        "vars": [
            {
                "name": "Bridge Token",
                "attr_path": "channels.whatsapp.bridge_token",
                "prompt": "Set a shared secret for bridge authentication (any string)",
                "password": True,
                "is_allowlist": False,
                "help": "A shared secret between Velo and the WhatsApp bridge",
            },
            {
                "name": "Allowed Users",
                "attr_path": "channels.whatsapp.allow_from",
                "prompt": "Phone numbers to allow (comma-separated, leave empty for all)",
                "password": False,
                "is_allowlist": True,
                "help": "Restricts who can talk to the bot. Empty means everyone.",
            },
        ],
    },
    # ── Matrix ────────────────────────────────────────────────
    {
        "key": "matrix",
        "label": "Matrix",
        "emoji": "\U0001f30d",
        "setup_instructions": [
            "Register a bot account on your Matrix homeserver (e.g. matrix.org)",
            "Log in with the bot account using Element or another client",
            "Go to Settings > Help & About to find the Access Token",
            "Note the user ID (e.g. @bot:matrix.org) and device ID",
        ],
        "vars": [
            {
                "name": "Homeserver URL",
                "attr_path": "channels.matrix.homeserver",
                "prompt": "Matrix homeserver URL (e.g. https://matrix.org)",
                "password": False,
                "is_allowlist": False,
                "help": "The base URL of your Matrix homeserver",
            },
            {
                "name": "Access Token",
                "attr_path": "channels.matrix.access_token",
                "prompt": "Paste your Matrix access token",
                "password": True,
                "is_allowlist": False,
                "help": "The access token from your bot account settings",
            },
            {
                "name": "User ID",
                "attr_path": "channels.matrix.user_id",
                "prompt": "Bot user ID (e.g. @bot:matrix.org)",
                "password": False,
                "is_allowlist": False,
                "help": "The full Matrix user ID for the bot account",
            },
            {
                "name": "Device ID",
                "attr_path": "channels.matrix.device_id",
                "prompt": "Device ID for the bot session",
                "password": False,
                "is_allowlist": False,
                "help": "The device ID assigned when the bot logged in",
            },
            {
                "name": "Allowed Users",
                "attr_path": "channels.matrix.allow_from",
                "prompt": "Matrix user IDs to allow (comma-separated, leave empty for all)",
                "password": False,
                "is_allowlist": True,
                "help": "Restricts who can talk to the bot. Empty means everyone.",
            },
        ],
    },
]


# ── Non-credential field names (never trigger auto-enable) ───────────
_ALLOWLIST_FIELDS = frozenset({"allow_from", "group_allow_from"})


def _is_credential_field(field_name: str) -> bool:
    """Return True if *field_name* is a credential (not an allowlist or flag).

    Args:
        field_name: The final segment of a dot-path (e.g. ``"token"``).

    Returns:
        True when the field holds a credential value.
    """
    return field_name not in _ALLOWLIST_FIELDS and field_name != "enabled"


def apply_platform_values(values: dict[str, Any], config_path: Path) -> None:
    """Write dot-path values into the Pydantic config and persist.

    Uses the existing Pydantic config system so that ``save_config`` produces
    camelCase JSON via ``model_dump(by_alias=True)``.

    Auto-sets ``enabled = True`` on the channel sub-config when at least one
    credential (non-allowlist) value is provided.

    Args:
        values: Mapping of dot-path keys (e.g. ``"channels.telegram.token"``)
            to their values.
        config_path: Path to the JSON config file.
    """
    config = load_config(config_path)

    # Track which channel sub-configs received a credential so we can auto-enable.
    channels_with_credentials: set[str] = set()

    for dot_path, value in values.items():
        parts = dot_path.split(".")
        # Traverse the model to the parent of the final attribute.
        obj = config
        for segment in parts[:-1]:
            obj = getattr(obj, segment)
        final_field = parts[-1]
        setattr(obj, final_field, value)

        # Reason: Only credential fields (tokens, secrets, URLs) trigger auto-enable.
        # Allowlists and the enabled flag itself should not.
        if len(parts) >= 3 and parts[0] == "channels" and _is_credential_field(final_field):
            channels_with_credentials.add(parts[1])

    # Auto-enable channels that received at least one credential.
    for channel_key in channels_with_credentials:
        channel_cfg = getattr(config.channels, channel_key)
        setattr(channel_cfg, "enabled", True)

    save_config(config, config_path)


def run_platform_setup(config_path: Path) -> None:
    """Interactive CLI flow for selecting and configuring chat platforms.

    Shows a numbered list of platforms, lets the user pick one, displays setup
    instructions, prompts for each variable, and persists via
    ``apply_platform_values``.  Loops until the user types ``"done"``.

    Args:
        config_path: Path to the JSON config file.
    """
    while True:
        # ── Show platform menu ───────────────────────────────────
        print("\n  Available platforms:\n")
        for idx, platform in enumerate(PLATFORMS, start=1):
            print(f"    {idx}. {platform['emoji']}  {platform['label']}")
        print(f"    {'done':>4}  Finish setup\n")

        choice = input("  Select a platform (number or 'done'): ").strip().lower()

        if choice == "done":
            break

        # Validate numeric selection.
        try:
            selection = int(choice)
        except ValueError:
            print("  Invalid choice. Enter a number or 'done'.")
            continue

        if selection < 1 or selection > len(PLATFORMS):
            print(f"  Invalid choice. Enter 1-{len(PLATFORMS)} or 'done'.")
            continue

        platform = PLATFORMS[selection - 1]

        # ── Show setup instructions ──────────────────────────────
        print(f"\n  {platform['emoji']}  {platform['label']} Setup\n")
        for step_num, instruction in enumerate(platform["setup_instructions"], start=1):
            print(f"    {step_num}. {instruction}")
        print()

        # ── Prompt for each variable ─────────────────────────────
        collected: dict[str, Any] = {}
        for var in platform["vars"]:
            help_suffix = f" ({var['help']})" if var.get("help") else ""
            prompt_text = f"  {var['prompt']}{help_suffix}: "

            if var.get("password"):
                raw = getpass.getpass(prompt=prompt_text)
            else:
                raw = input(prompt_text).strip()

            if not raw:
                continue  # Skip empty inputs.

            if var.get("is_allowlist"):
                # Reason: Comma-separated input is split into a list for
                # Pydantic list fields like allow_from.
                value: Any = [item.strip() for item in raw.split(",") if item.strip()]
            else:
                value = raw

            collected[var["attr_path"]] = value

        if collected:
            apply_platform_values(collected, config_path)
            print(f"\n  {platform['label']} configured successfully.")
        else:
            print(f"\n  No values provided for {platform['label']}. Skipping.")
