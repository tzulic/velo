"""Platform setup wizard registry.

Each entry describes a chat platform that the onboarding wizard can configure.
The ``attr_path`` values map to Pydantic fields in ``velo.config.schema.ChannelsConfig``
so the wizard can write values into ``~/.velo/config.json`` at the correct location.
"""

from typing import Any

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
