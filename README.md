# Velo

An open-source personal AI assistant that lives on your server and talks to you through your favorite chat apps.

Velo runs as a long-lived daemon process. It connects to Telegram, Discord, WhatsApp, Slack, and other platforms — routing your messages through an LLM with tools, persistent memory, and a growing skill set. You configure it once, and it stays on.

**[Volos](https://volos.one)** is the managed service that deploys and maintains Velo for you. If you'd rather not self-host, Volos handles everything — infrastructure, updates, configuration, API keys.

## What Velo Does

- **Talks to you** on Telegram, Discord, WhatsApp, Slack, Email, Matrix, and 6 more platforms — all at once
- **Remembers** conversations across sessions with a three-layer memory system (agent notes, user profile, searchable history)
- **Uses tools** — reads/writes files, runs shell commands, browses the web, searches the internet, manages cron jobs
- **Learns new skills** — discovers, installs, and even creates its own skills during conversation
- **Connects to anything** via MCP (Model Context Protocol) — same config format as Claude Desktop
- **Runs background tasks** — spawns subagents, schedules cron jobs, wakes up periodically to check on things
- **Works with 20+ LLM providers** — Anthropic, OpenAI, Gemini, Mistral, DeepSeek, Groq, OpenRouter, and more via native SDKs (no LiteLLM)

## Architecture

```
Channels (Telegram, WhatsApp, Discord, Slack, Email, ...)
    │ InboundMessage
    ▼
MessageBus (async queues: inbound → agent, outbound ← agent)
    │
    ▼
AgentLoop
  ├── ContextBuilder (system prompt + memory + skills + Honcho user context)
  ├── ToolRegistry (active tools sent to LLM, deferred tools discovered on demand)
  ├── MemoryStore (MEMORY.md, USER.md, HISTORY.md — consolidated by the LLM)
  ├── SubagentManager (background task spawning, shared iteration budget)
  └── SessionManager (per-session message history, JSONL or SQLite with FTS5)
    │
    ▼
LLM Providers (native SDKs: Anthropic, OpenAI, Mistral, Gemini, Azure, ...)
```

Messages flow in from channels, get processed by the agent loop (which may call tools multiple times), and flow back out as responses. Different chat sessions run in parallel; messages within the same session are processed in order.

For full technical details, see [TECHNICAL_REFERENCE.md](TECHNICAL_REFERENCE.md).

## Get Started

### Managed (Recommended)

Sign up at **[volos.one](https://volos.one)** — Volos handles deployment, updates, API keys, and infrastructure. You just chat.

### Self-Hosted

**Install with [uv](https://github.com/astral-sh/uv)** (recommended):

```bash
uv tool install velo-ai
```

Or from PyPI:

```bash
pip install velo-ai
```

Or from source:

```bash
git clone https://github.com/tzulic/velo.git
cd velo
pip install -e .
```

### Quick Start

> [!TIP]
> You need at least one LLM provider API key. [OpenRouter](https://openrouter.ai/keys) gives you access to all models with a single key. For web search, optionally add a [Parallel.ai](https://platform.parallel.ai) key.

**1. Initialize**

```bash
velo onboard
```

**2. Configure** (`~/.velo/config.json`)

```json
{
  "providers": {
    "openrouter": {
      "apiKey": "sk-or-v1-xxx"
    }
  },
  "agents": {
    "defaults": {
      "model": "anthropic/claude-sonnet-4-6"
    }
  }
}
```

**3. Chat**

```bash
velo agent
```

That's it. You have a working AI assistant.

### Update

```bash
# uv
uv tool upgrade velo-ai

# pip
pip install -U velo-ai
```

If you use WhatsApp, rebuild the bridge after upgrading: `rm -rf ~/.velo/bridge && velo channels login`

## Chat Channels

Connect Velo to one or more chat platforms. Enable a channel in your config, run `velo gateway`, and it starts listening.

| Channel | What you need | Transport |
|---------|---------------|-----------|
| **Telegram** | Bot token from @BotFather | Long polling |
| **Discord** | Bot token + Message Content intent | Gateway WebSocket |
| **WhatsApp** | QR code scan (Node.js required) | Bridge WebSocket |
| **Slack** | Bot token + App-Level token | Socket Mode |
| **Email** | IMAP/SMTP credentials | Polling + SMTP |
| **Matrix** | Access token + device ID | matrix-nio (E2EE supported) |
| **Feishu** | App ID + App Secret | WebSocket |
| **DingTalk** | App Key + App Secret | Stream Mode |
| **QQ** | App ID + App Secret | botpy SDK |
| **Mochat** | Claw token | Socket.IO |

Every channel has an `allowFrom` list. Empty = deny all. `["*"]` = allow everyone. For group chats, `groupPolicy` controls whether the agent responds to all messages (`"open"`) or only when mentioned (`"mention"`).

<details>
<summary><b>Telegram</b></summary>

**1. Create a bot** — Open Telegram, search `@BotFather`, send `/newbot`, copy the token.

**2. Configure**

```json
{
  "channels": {
    "telegram": {
      "enabled": true,
      "token": "YOUR_BOT_TOKEN",
      "allowFrom": ["YOUR_USER_ID"]
    }
  }
}
```

**3. Run** — `velo gateway`

</details>

<details>
<summary><b>Discord</b></summary>

**1. Create a bot** — Go to https://discord.com/developers/applications, create an app, add a bot, copy the token. Enable **MESSAGE CONTENT INTENT** in Bot settings.

**2. Get your User ID** — Discord Settings → Advanced → Developer Mode → right-click avatar → Copy User ID.

**3. Configure**

```json
{
  "channels": {
    "discord": {
      "enabled": true,
      "token": "YOUR_BOT_TOKEN",
      "allowFrom": ["YOUR_USER_ID"],
      "groupPolicy": "mention"
    }
  }
}
```

**4. Invite the bot** — OAuth2 → URL Generator → Scopes: `bot` → Permissions: `Send Messages`, `Read Message History` → open the invite URL.

**5. Run** — `velo gateway`

</details>

<details>
<summary><b>WhatsApp</b></summary>

Requires **Node.js 18+**.

**1. Link device**

```bash
velo channels login
# Scan QR with WhatsApp → Settings → Linked Devices
```

**2. Configure**

```json
{
  "channels": {
    "whatsapp": {
      "enabled": true,
      "allowFrom": ["+1234567890"]
    }
  }
}
```

**3. Run** (two terminals)

```bash
velo channels login   # Terminal 1 — keeps the bridge alive
velo gateway          # Terminal 2 — starts the agent
```

</details>

<details>
<summary><b>Slack</b></summary>

Uses Socket Mode — no public URL required.

**1. Create a Slack app** — [Slack API](https://api.slack.com/apps) → Create New App → "From scratch".

**2. Configure the app:**
- Socket Mode ON → generate App-Level Token (`xapp-...`)
- OAuth & Permissions → bot scopes: `chat:write`, `reactions:write`, `app_mentions:read`
- Event Subscriptions ON → subscribe to: `message.im`, `message.channels`, `app_mention`
- App Home → Messages Tab ON → allow DMs
- Install to Workspace → copy Bot Token (`xoxb-...`)

**3. Configure**

```json
{
  "channels": {
    "slack": {
      "enabled": true,
      "botToken": "xoxb-...",
      "appToken": "xapp-...",
      "allowFrom": ["YOUR_SLACK_USER_ID"],
      "groupPolicy": "mention"
    }
  }
}
```

**4. Run** — `velo gateway`

</details>

<details>
<summary><b>Email</b></summary>

Velo polls IMAP for incoming mail and replies via SMTP.

**1. Get credentials** (Gmail example) — Create a dedicated Gmail account, enable 2FA, create an App Password.

**2. Configure**

```json
{
  "channels": {
    "email": {
      "enabled": true,
      "consentGranted": true,
      "imapHost": "imap.gmail.com",
      "imapPort": 993,
      "imapUsername": "my-velo@gmail.com",
      "imapPassword": "your-app-password",
      "smtpHost": "smtp.gmail.com",
      "smtpPort": 587,
      "smtpUsername": "my-velo@gmail.com",
      "smtpPassword": "your-app-password",
      "fromAddress": "my-velo@gmail.com",
      "allowFrom": ["your-real-email@gmail.com"]
    }
  }
}
```

**3. Run** — `velo gateway`

</details>

<details>
<summary><b>Matrix</b></summary>

Install with Matrix support: `pip install velo-ai[matrix]`

E2EE is on by default. Keep a stable `deviceId` and persistent store — encrypted session state is lost if these change.

```json
{
  "channels": {
    "matrix": {
      "enabled": true,
      "homeserver": "https://matrix.org",
      "userId": "@velo:matrix.org",
      "accessToken": "syt_xxx",
      "deviceId": "VELO01",
      "e2eeEnabled": true,
      "allowFrom": ["@your_user:matrix.org"]
    }
  }
}
```

Run: `velo gateway`

</details>

<details>
<summary><b>Feishu, DingTalk, QQ</b></summary>

All three use WebSocket/stream connections — no public IP required.

**Feishu:** Create an app on [Feishu Open Platform](https://open.feishu.cn/app), enable Bot capability, add `im:message` permissions, select Long Connection mode.

```json
{ "channels": { "feishu": { "enabled": true, "appId": "cli_xxx", "appSecret": "xxx", "allowFrom": ["ou_YOUR_OPEN_ID"] } } }
```

**DingTalk:** Create an app on [DingTalk Open Platform](https://open-dev.dingtalk.com/), add Robot capability, toggle Stream Mode ON.

```json
{ "channels": { "dingtalk": { "enabled": true, "clientId": "YOUR_APP_KEY", "clientSecret": "YOUR_APP_SECRET", "allowFrom": ["YOUR_STAFF_ID"] } } }
```

**QQ:** Register at [QQ Open Platform](https://q.qq.com), create a bot, copy AppID and AppSecret.

```json
{ "channels": { "qq": { "enabled": true, "appId": "YOUR_APP_ID", "secret": "YOUR_APP_SECRET", "allowFrom": ["YOUR_OPENID"] } } }
```

Run: `velo gateway`

</details>

## Providers

Velo talks to LLMs through native SDKs — no abstraction layer in between. Provider auto-detection matches model names to the right SDK. Set `"provider": "auto"` (the default) and Velo figures out which SDK to use based on the model name.

| Provider | SDK | Get API Key |
|----------|-----|-------------|
| `anthropic` | Native Anthropic SDK | [console.anthropic.com](https://console.anthropic.com) |
| `openai` | Native OpenAI SDK | [platform.openai.com](https://platform.openai.com) |
| `gemini` | Native Google GenAI SDK | [aistudio.google.com](https://aistudio.google.com) |
| `mistral` | Native Mistral SDK | [console.mistral.ai](https://console.mistral.ai) |
| `openrouter` | OpenAI-compatible | [openrouter.ai](https://openrouter.ai) |
| `deepseek` | OpenAI-compatible | [platform.deepseek.com](https://platform.deepseek.com) |
| `groq` | OpenAI-compatible | [console.groq.com](https://console.groq.com) |
| `xai` | OpenAI-compatible | [console.x.ai](https://console.x.ai) |
| `azure_openai` | Azure OpenAI SDK | [portal.azure.com](https://portal.azure.com) |
| `aihubmix` | OpenAI-compatible | [aihubmix.com](https://aihubmix.com) |
| `siliconflow` | OpenAI-compatible | [siliconflow.cn](https://siliconflow.cn) |
| `volcengine` | OpenAI-compatible | [volcengine.com](https://www.volcengine.com) |
| `dashscope` | OpenAI-compatible | [dashscope.console.aliyun.com](https://dashscope.console.aliyun.com) |
| `moonshot` | OpenAI-compatible | [platform.moonshot.cn](https://platform.moonshot.cn) |
| `zhipu` | OpenAI-compatible | [open.bigmodel.cn](https://open.bigmodel.cn) |
| `minimax` | OpenAI-compatible | [platform.minimaxi.com](https://platform.minimaxi.com) |
| `vllm` | OpenAI-compatible | Local — any OpenAI-compatible server |
| `custom` | OpenAI-compatible | Any endpoint (LM Studio, llama.cpp, Together AI, etc.) |
| `openai_codex` | OAuth | `velo provider login openai-codex` |
| `github_copilot` | OAuth | `velo provider login github-copilot` |

> [!TIP]
> Groq provides free voice transcription via Whisper. If configured, Telegram voice messages are automatically transcribed.

<details>
<summary><b>Custom / local provider</b></summary>

Connect to any OpenAI-compatible endpoint:

```json
{
  "providers": {
    "custom": {
      "apiKey": "your-api-key",
      "apiBase": "https://api.your-provider.com/v1"
    }
  },
  "agents": {
    "defaults": {
      "model": "your-model-name"
    }
  }
}
```

For local servers that don't need a key, set `apiKey` to any non-empty string.

</details>

<details>
<summary><b>Adding a new provider (developer guide)</b></summary>

Velo uses a Provider Registry (`velo/providers/registry.py`) as the single source of truth. Adding a provider takes two steps:

**Step 1.** Add a `ProviderSpec` to `PROVIDERS` in `velo/providers/registry.py`:

```python
ProviderSpec(
    name="myprovider",
    keywords=("myprovider", "mymodel"),
    display_name="My Provider",
    provider_type="openai",  # or "anthropic", "mistral", "gemini"
)
```

**Step 2.** Add a field to `ProvidersConfig` in `velo/config/schema.py`:

```python
myprovider: ProviderConfig = ProviderConfig()
```

If the provider uses a standard OpenAI-compatible API, that's it. If it needs a novel SDK, implement an `LLMProvider` subclass.

</details>

## MCP (Model Context Protocol)

Connect external tool servers as native agent tools. Config format is compatible with Claude Desktop / Cursor — copy configs directly from MCP server READMEs.

```json
{
  "tools": {
    "mcpServers": {
      "filesystem": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/dir"]
      },
      "my-remote-mcp": {
        "url": "https://example.com/mcp/",
        "headers": { "Authorization": "Bearer xxxxx" }
      }
    }
  }
}
```

Supports both stdio (`command` + `args`) and HTTP (`url` + `headers`). MCP tools start in the deferred pool and are activated on demand when the agent searches for them — keeping context lean.

## Skills

Skills are markdown files that teach the agent how to use specific tools or follow specific workflows. They live in `workspace/skills/` (yours) and `velo/skills/` (built-in). Workspace skills override built-ins of the same name.

**Built-in skills:** GitHub, weather, cron, memory management, tmux, summarization, skill creation.

The agent can also create new skills during conversation via the `skill_manage` tool. All skill writes are security-scanned before saving.

## Memory

Velo remembers things across sessions through three files in `workspace/memory/`:

| File | What it stores |
|------|----------------|
| `MEMORY.md` | Agent notes — environment facts, project context, conventions |
| `USER.md` | User profile — name, preferences, timezone, communication style |
| `HISTORY.md` | Searchable log of past session summaries |

When enough messages accumulate (default: 100), the agent consolidates them — summarizing the conversation into these files via a separate LLM call. All writes are atomic (crash-safe).

When [Honcho](https://honcho.dev) is configured, it handles user modeling (cross-session identity, preferences, peer cards). Local `MEMORY.md` focuses on agent-operational facts; Honcho handles user personalization.

## Security

| Setting | Default | What it does |
|---------|---------|-------------|
| `tools.restrictToWorkspace` | `false` | Sandboxes all file and shell operations to the workspace directory |
| `tools.exec.extendedSafety` | `true` | Blocks dangerous shell patterns (rm -rf /, reverse shells, privilege escalation, credential leakage) |
| `channels.*.allowFrom` | `[]` (deny all) | Allowlist of user IDs per channel |

Additional protections: memory writes are scanned for prompt injection, external web content is wrapped in boundary markers, group chats automatically disable side-effecting tools (shell, file write, cron, spawn), and skill writes are security-gated by trust level.

## CLI Reference

| Command | Description |
|---------|-------------|
| `velo onboard` | Initialize config and workspace |
| `velo agent` | Interactive chat (REPL) |
| `velo agent -m "..."` | Send a single message |
| `velo agent -c <config>` | Use a specific config file |
| `velo agent -w <workspace>` | Use a specific workspace |
| `velo gateway` | Start the gateway (all channels, cron, heartbeat) |
| `velo gateway --port 18790` | Override gateway port |
| `velo status` | Show config, workspace, and provider status |
| `velo channels login` | Link WhatsApp (QR code scan) |
| `velo channels status` | Show channel status |
| `velo provider login <name>` | OAuth login (e.g. `openai-codex`) |

**In-chat commands:** `/new` (clear session), `/memory` (show memory), `/subagents` (list background tasks), `/cancel` (stop subagents), `/sessions` (list sessions).

Exit interactive mode: `exit`, `quit`, `/exit`, `:q`, or `Ctrl+D`.

<details>
<summary><b>Heartbeat (periodic tasks)</b></summary>

The gateway wakes up every 30 minutes and checks `HEARTBEAT.md` in your workspace. If there are tasks, the agent executes them and delivers results to your most recently active chat.

Edit `~/.velo/workspace/HEARTBEAT.md`:

```markdown
## Periodic Tasks

- [ ] Check weather forecast and send a summary
- [ ] Scan inbox for urgent emails
```

The agent can also manage this file itself — ask it to "add a periodic task."

</details>

<details>
<summary><b>Multiple instances</b></summary>

Run multiple Velo instances with separate configs:

```bash
velo gateway --config ~/.velo-telegram/config.json
velo gateway --config ~/.velo-discord/config.json --port 18791
```

Each instance needs its own port, config file, and workspace. Runtime data (sessions, memory, cron) is derived from the config directory.

```bash
# CLI against a specific instance
velo agent -c ~/.velo-telegram/config.json -m "Hello"
```

</details>

## Docker

```bash
# Docker Compose
docker compose run --rm velo-cli onboard    # first-time setup
vim ~/.velo/config.json                      # add API keys
docker compose up -d velo-gateway            # start gateway

# Or plain Docker
docker build -t velo .
docker run -v ~/.velo:/root/.velo --rm velo onboard
docker run -v ~/.velo:/root/.velo -p 18790:18790 velo gateway
```

<details>
<summary><b>systemd service (Linux)</b></summary>

Create `~/.config/systemd/user/velo-gateway.service`:

```ini
[Unit]
Description=Velo Gateway
After=network.target

[Service]
Type=simple
ExecStart=%h/.local/bin/velo gateway
Restart=always
RestartSec=10

[Install]
WantedBy=default.target
```

```bash
systemctl --user daemon-reload
systemctl --user enable --now velo-gateway
journalctl --user -u velo-gateway -f         # follow logs
```

To keep running after logout: `loginctl enable-linger $USER`

</details>

## Project Structure

```
velo/
├── agent/         Core agent loop, context builder, memory, subagents, security
│   └── tools/     Built-in tools (filesystem, shell, web, spawn, cron, MCP, ...)
├── providers/     LLM providers (Anthropic, OpenAI, Mistral, Gemini, Azure, ...)
├── channels/      Chat platform integrations (13 channels)
├── bus/           Async message bus (inbound/outbound queues)
├── session/       Session management (JSONL, SQLite with FTS5)
├── config/        Pydantic settings schema + loader
├── plugins/       Plugin system (hooks, context providers, services)
├── skills/        Built-in skills (github, weather, cron, memory, ...)
├── a2a/           Agent-to-agent protocol
├── cron/          Scheduled tasks
├── heartbeat/     Proactive wake-up service
└── cli/           Typer CLI commands
```

## Acknowledgments

Velo builds on the work of **[NanoBot](https://github.com/HKUDS/nanobot)** (HKUDS), **[Hermes Agent](https://github.com/NousResearch/hermes-agent)** (Nous Research), and **[OpenClaw](https://github.com/openclaw/openclaw)**. Thank you for the foundation.

## Contributing

PRs welcome on [GitHub](https://github.com/tzulic/velo). The codebase is intentionally readable.

```bash
# Dev setup
git clone https://github.com/tzulic/velo.git
cd velo
pip install -e ".[dev]"

# Run tests
uv run pytest -v

# Lint
uv run ruff check .
uv run ruff format .
```

## License

MIT — see [LICENSE](LICENSE).

---

**[Volos](https://volos.one)** deploys and manages Velo so you don't have to. Your AI assistant, fully managed.
