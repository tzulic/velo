<div align="center">
  <img src="velo_logo.png" alt="velo" width="500">
  <h1>velo: Ultra-Lightweight Personal AI Assistant</h1>
  <p>
    <a href="https://pypi.org/project/velo-ai/"><img src="https://img.shields.io/pypi/v/velo-ai" alt="PyPI"></a>
    <a href="https://pepy.tech/project/velo-ai"><img src="https://static.pepy.tech/badge/velo-ai" alt="Downloads"></a>
    <img src="https://img.shields.io/badge/python-≥3.11-blue" alt="Python">
    <img src="https://img.shields.io/badge/license-MIT-green" alt="License">
    <a href="./COMMUNICATION.md"><img src="https://img.shields.io/badge/Feishu-Group-E9DBFC?style=flat&logo=feishu&logoColor=white" alt="Feishu"></a>
    <a href="./COMMUNICATION.md"><img src="https://img.shields.io/badge/WeChat-Group-C5EAB4?style=flat&logo=wechat&logoColor=white" alt="WeChat"></a>
    <a href="https://discord.gg/MnCvHqpUGB"><img src="https://img.shields.io/badge/Discord-Community-5865F2?style=flat&logo=discord&logoColor=white" alt="Discord"></a>
  </p>
</div>

💨 **velo** is an **ultra-lightweight** personal AI assistant inspired by [OpenClaw](https://github.com/openclaw/openclaw).

⚡️ Delivers core agent functionality with **99% fewer lines of code** than OpenClaw.

📏 Real-time line count: run `bash core_agent_lines.sh` to verify anytime.

## 📢 News

- **2026-03-08** 🚀 Released **v0.1.4.post4** — a reliability-packed release with safer defaults, better multi-instance support, sturdier MCP, and major channel and provider improvements. Please see [release notes](https://github.com/HKUDS/velo/releases/tag/v0.1.4.post4) for details.
- **2026-03-07** 🚀 Azure OpenAI provider, WhatsApp media, QQ group chats, and more Telegram/Feishu polish.
- **2026-03-06** 🪄 Lighter providers, smarter media handling, and sturdier memory and CLI compatibility.
- **2026-03-05** ⚡️ Telegram draft streaming, MCP SSE support, and broader channel reliability fixes.
- **2026-03-04** 🛠️ Dependency cleanup, safer file reads, and another round of test and Cron fixes.
- **2026-03-03** 🧠 Cleaner user-message merging, safer multimodal saves, and stronger Cron guards.
- **2026-03-02** 🛡️ Safer default access control, sturdier Cron reloads, and cleaner Matrix media handling.
- **2026-03-01** 🌐 Web proxy support, smarter Cron reminders, and Feishu rich-text parsing improvements.
- **2026-02-28** 🚀 Released **v0.1.4.post3** — cleaner context, hardened session history, and smarter agent. Please see [release notes](https://github.com/HKUDS/velo/releases/tag/v0.1.4.post3) for details.
- **2026-02-27** 🧠 Experimental thinking mode support, DingTalk media messages, Feishu and QQ channel fixes.
- **2026-02-26** 🛡️ Session poisoning fix, WhatsApp dedup, Windows path guard, Mistral compatibility.

<details>
<summary>Earlier news</summary>

- **2026-02-25** 🧹 New Matrix channel, cleaner session context, auto workspace template sync.
- **2026-02-24** 🚀 Released **v0.1.4.post2** — a reliability-focused release with a redesigned heartbeat, prompt cache optimization, and hardened provider & channel stability. See [release notes](https://github.com/HKUDS/velo/releases/tag/v0.1.4.post2) for details.
- **2026-02-23** 🔧 Virtual tool-call heartbeat, prompt cache optimization, Slack mrkdwn fixes.
- **2026-02-22** 🛡️ Slack thread isolation, Discord typing fix, agent reliability improvements.
- **2026-02-21** 🎉 Released **v0.1.4.post1** — new providers, media support across channels, and major stability improvements. See [release notes](https://github.com/HKUDS/velo/releases/tag/v0.1.4.post1) for details.
- **2026-02-20** 🐦 Feishu now receives multimodal files from users. More reliable memory under the hood.
- **2026-02-19** ✨ Slack now sends files, Discord splits long messages, and subagents work in CLI mode.
- **2026-02-18** ⚡️ velo now supports VolcEngine, MCP custom auth headers, and Anthropic prompt caching.
- **2026-02-17** 🎉 Released **v0.1.4** — MCP support, progress streaming, new providers, and multiple channel improvements. Please see [release notes](https://github.com/HKUDS/velo/releases/tag/v0.1.4) for details.
- **2026-02-16** 🦞 velo now integrates a [ClawHub](https://clawhub.ai) skill — search and install public agent skills.
- **2026-02-15** 🔑 velo now supports OpenAI Codex provider with OAuth login support.
- **2026-02-14** 🔌 velo now supports MCP! See [MCP section](#mcp-model-context-protocol) for details.
- **2026-02-13** 🎉 Released **v0.1.3.post7** — includes security hardening and multiple improvements. **Please upgrade to the latest version to address security issues**. See [release notes](https://github.com/HKUDS/velo/releases/tag/v0.1.3.post7) for more details.
- **2026-02-12** 🧠 Redesigned memory system — Less code, more reliable. Join the [discussion](https://github.com/HKUDS/velo/discussions/566) about it!
- **2026-02-11** ✨ Enhanced CLI experience and added MiniMax support!
- **2026-02-10** 🎉 Released **v0.1.3.post6** with improvements! Check the updates [notes](https://github.com/HKUDS/velo/releases/tag/v0.1.3.post6) and our [roadmap](https://github.com/HKUDS/velo/discussions/431).
- **2026-02-09** 💬 Added Slack, Email, and QQ support — velo now supports multiple chat platforms!
- **2026-02-08** 🔧 Refactored Providers—adding a new LLM provider now takes just 2 simple steps! Check [here](#providers).
- **2026-02-07** 🚀 Released **v0.1.3.post5** with Qwen support & several key improvements! Check [here](https://github.com/HKUDS/velo/releases/tag/v0.1.3.post5) for details.
- **2026-02-06** ✨ Added Moonshot/Kimi provider, Discord integration, and enhanced security hardening!
- **2026-02-05** ✨ Added Feishu channel, DeepSeek provider, and enhanced scheduled tasks support!
- **2026-02-04** 🚀 Released **v0.1.3.post4** with multi-provider & Docker support! Check [here](https://github.com/HKUDS/velo/releases/tag/v0.1.3.post4) for details.
- **2026-02-03** ⚡ Integrated vLLM for local LLM support and improved natural language task scheduling!
- **2026-02-02** 🎉 velo officially launched! Welcome to try 🐈 velo!

</details>

## Key Features of velo:

🪶 **Ultra-Lightweight**: Just ~4,000 lines of core agent code — 99% smaller than Clawdbot.

🔬 **Research-Ready**: Clean, readable code that's easy to understand, modify, and extend for research.

⚡️ **Lightning Fast**: Minimal footprint means faster startup, lower resource usage, and quicker iterations.

💎 **Easy-to-Use**: One-click to deploy and you're ready to go.

## 🏗️ Architecture

<p align="center">
  <img src="velo_arch.png" alt="velo architecture" width="800">
</p>

## ✨ Features

<table align="center">
  <tr align="center">
    <th><p align="center">📈 24/7 Real-Time Market Analysis</p></th>
    <th><p align="center">🚀 Full-Stack Software Engineer</p></th>
    <th><p align="center">📅 Smart Daily Routine Manager</p></th>
    <th><p align="center">📚 Personal Knowledge Assistant</p></th>
  </tr>
  <tr>
    <td align="center"><p align="center"><img src="case/search.gif" width="180" height="400"></p></td>
    <td align="center"><p align="center"><img src="case/code.gif" width="180" height="400"></p></td>
    <td align="center"><p align="center"><img src="case/scedule.gif" width="180" height="400"></p></td>
    <td align="center"><p align="center"><img src="case/memory.gif" width="180" height="400"></p></td>
  </tr>
  <tr>
    <td align="center">Discovery • Insights • Trends</td>
    <td align="center">Develop • Deploy • Scale</td>
    <td align="center">Schedule • Automate • Organize</td>
    <td align="center">Learn • Memory • Reasoning</td>
  </tr>
</table>

## 📦 Install

**Install from source** (latest features, recommended for development)

```bash
git clone https://github.com/HKUDS/velo.git
cd velo
pip install -e .
```

**Install with [uv](https://github.com/astral-sh/uv)** (stable, fast)

```bash
uv tool install velo-ai
```

**Install from PyPI** (stable)

```bash
pip install velo-ai
```

### Update to latest version

**PyPI / pip**

```bash
pip install -U velo-ai
velo --version
```

**uv**

```bash
uv tool upgrade velo-ai
velo --version
```

**Using WhatsApp?** Rebuild the local bridge after upgrading:

```bash
rm -rf ~/.velo/bridge
velo channels login
```

## 🚀 Quick Start

> [!TIP]
> Set your API key in `~/.velo/config.json`.
> Get API keys: [OpenRouter](https://openrouter.ai/keys) (Global) · [Parallel.ai](https://platform.parallel.ai) (optional, for web search & fetch)

**1. Initialize**

```bash
velo onboard
```

**2. Configure** (`~/.velo/config.json`)

Add or merge these **two parts** into your config (other options have defaults).

*Set your API key* (e.g. OpenRouter, recommended for global users):
```json
{
  "providers": {
    "openrouter": {
      "apiKey": "sk-or-v1-xxx"
    }
  }
}
```

*Set your model* (optionally pin a provider — defaults to auto-detection):
```json
{
  "agents": {
    "defaults": {
      "model": "anthropic/claude-opus-4-5",
      "provider": "openrouter"
    }
  }
}
```

**3. Chat**

```bash
velo agent
```

That's it! You have a working AI assistant in 2 minutes.

## 💬 Chat Apps

Connect velo to your favorite chat platform.

| Channel | What you need |
|---------|---------------|
| **Telegram** | Bot token from @BotFather |
| **Discord** | Bot token + Message Content intent |
| **WhatsApp** | QR code scan |
| **Feishu** | App ID + App Secret |
| **Mochat** | Claw token (auto-setup available) |
| **DingTalk** | App Key + App Secret |
| **Slack** | Bot token + App-Level token |
| **Email** | IMAP/SMTP credentials |
| **QQ** | App ID + App Secret |

<details>
<summary><b>Telegram</b> (Recommended)</summary>

**1. Create a bot**
- Open Telegram, search `@BotFather`
- Send `/newbot`, follow prompts
- Copy the token

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

> You can find your **User ID** in Telegram settings. It is shown as `@yourUserId`.
> Copy this value **without the `@` symbol** and paste it into the config file.


**3. Run**

```bash
velo gateway
```

</details>

<details>
<summary><b>Mochat (Claw IM)</b></summary>

Uses **Socket.IO WebSocket** by default, with HTTP polling fallback.

**1. Ask velo to set up Mochat for you**

Simply send this message to velo (replace `xxx@xxx` with your real email):

```
Read https://raw.githubusercontent.com/HKUDS/MoChat/refs/heads/main/skills/velo/skill.md and register on MoChat. My Email account is xxx@xxx Bind me as your owner and DM me on MoChat.
```

velo will automatically register, configure `~/.velo/config.json`, and connect to Mochat.

**2. Restart gateway**

```bash
velo gateway
```

That's it — velo handles the rest!

<br>

<details>
<summary>Manual configuration (advanced)</summary>

If you prefer to configure manually, add the following to `~/.velo/config.json`:

> Keep `claw_token` private. It should only be sent in `X-Claw-Token` header to your Mochat API endpoint.

```json
{
  "channels": {
    "mochat": {
      "enabled": true,
      "base_url": "https://mochat.io",
      "socket_url": "https://mochat.io",
      "socket_path": "/socket.io",
      "claw_token": "claw_xxx",
      "agent_user_id": "6982abcdef",
      "sessions": ["*"],
      "panels": ["*"],
      "reply_delay_mode": "non-mention",
      "reply_delay_ms": 120000
    }
  }
}
```



</details>

</details>

<details>
<summary><b>Discord</b></summary>

**1. Create a bot**
- Go to https://discord.com/developers/applications
- Create an application → Bot → Add Bot
- Copy the bot token

**2. Enable intents**
- In the Bot settings, enable **MESSAGE CONTENT INTENT**
- (Optional) Enable **SERVER MEMBERS INTENT** if you plan to use allow lists based on member data

**3. Get your User ID**
- Discord Settings → Advanced → enable **Developer Mode**
- Right-click your avatar → **Copy User ID**

**4. Configure**

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

> `groupPolicy` controls how the bot responds in group channels:
> - `"mention"` (default) — Only respond when @mentioned
> - `"open"` — Respond to all messages
> DMs always respond when the sender is in `allowFrom`.

**5. Invite the bot**
- OAuth2 → URL Generator
- Scopes: `bot`
- Bot Permissions: `Send Messages`, `Read Message History`
- Open the generated invite URL and add the bot to your server

**6. Run**

```bash
velo gateway
```

</details>

<details>
<summary><b>Matrix (Element)</b></summary>

Install Matrix dependencies first:

```bash
pip install velo-ai[matrix]
```

**1. Create/choose a Matrix account**

- Create or reuse a Matrix account on your homeserver (for example `matrix.org`).
- Confirm you can log in with Element.

**2. Get credentials**

- You need:
  - `userId` (example: `@velo:matrix.org`)
  - `accessToken`
  - `deviceId` (recommended so sync tokens can be restored across restarts)
- You can obtain these from your homeserver login API (`/_matrix/client/v3/login`) or from your client's advanced session settings.

**3. Configure**

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
      "allowFrom": ["@your_user:matrix.org"],
      "groupPolicy": "open",
      "groupAllowFrom": [],
      "allowRoomMentions": false,
      "maxMediaBytes": 20971520
    }
  }
}
```

> Keep a persistent `matrix-store` and stable `deviceId` — encrypted session state is lost if these change across restarts.

| Option | Description |
|--------|-------------|
| `allowFrom` | User IDs allowed to interact. Empty denies all; use `["*"]` to allow everyone. |
| `groupPolicy` | `open` (default), `mention`, or `allowlist`. |
| `groupAllowFrom` | Room allowlist (used when policy is `allowlist`). |
| `allowRoomMentions` | Accept `@room` mentions in mention mode. |
| `e2eeEnabled` | E2EE support (default `true`). Set `false` for plaintext-only. |
| `maxMediaBytes` | Max attachment size (default `20MB`). Set `0` to block all media. |




**4. Run**

```bash
velo gateway
```

</details>

<details>
<summary><b>WhatsApp</b></summary>

Requires **Node.js ≥18**.

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
# Terminal 1
velo channels login

# Terminal 2
velo gateway
```

> WhatsApp bridge updates are not applied automatically for existing installations.
> After upgrading velo, rebuild the local bridge with:
> `rm -rf ~/.velo/bridge && velo channels login`

</details>

<details>
<summary><b>Feishu (飞书)</b></summary>

Uses **WebSocket** long connection — no public IP required.

**1. Create a Feishu bot**
- Visit [Feishu Open Platform](https://open.feishu.cn/app)
- Create a new app → Enable **Bot** capability
- **Permissions**: Add `im:message` (send messages) and `im:message.p2p_msg:readonly` (receive messages)
- **Events**: Add `im.message.receive_v1` (receive messages)
  - Select **Long Connection** mode (requires running velo first to establish connection)
- Get **App ID** and **App Secret** from "Credentials & Basic Info"
- Publish the app

**2. Configure**

```json
{
  "channels": {
    "feishu": {
      "enabled": true,
      "appId": "cli_xxx",
      "appSecret": "xxx",
      "encryptKey": "",
      "verificationToken": "",
      "allowFrom": ["ou_YOUR_OPEN_ID"]
    }
  }
}
```

> `encryptKey` and `verificationToken` are optional for Long Connection mode.
> `allowFrom`: Add your open_id (find it in velo logs when you message the bot). Use `["*"]` to allow all users.

**3. Run**

```bash
velo gateway
```

> [!TIP]
> Feishu uses WebSocket to receive messages — no webhook or public IP needed!

</details>

<details>
<summary><b>QQ (QQ单聊)</b></summary>

Uses **botpy SDK** with WebSocket — no public IP required. Currently supports **private messages only**.

**1. Register & create bot**
- Visit [QQ Open Platform](https://q.qq.com) → Register as a developer (personal or enterprise)
- Create a new bot application
- Go to **开发设置 (Developer Settings)** → copy **AppID** and **AppSecret**

**2. Set up sandbox for testing**
- In the bot management console, find **沙箱配置 (Sandbox Config)**
- Under **在消息列表配置**, click **添加成员** and add your own QQ number
- Once added, scan the bot's QR code with mobile QQ → open the bot profile → tap "发消息" to start chatting

**3. Configure**

> - `allowFrom`: Add your openid (find it in velo logs when you message the bot). Use `["*"]` for public access.
> - For production: submit a review in the bot console and publish. See [QQ Bot Docs](https://bot.q.qq.com/wiki/) for the full publishing flow.

```json
{
  "channels": {
    "qq": {
      "enabled": true,
      "appId": "YOUR_APP_ID",
      "secret": "YOUR_APP_SECRET",
      "allowFrom": ["YOUR_OPENID"]
    }
  }
}
```

**4. Run**

```bash
velo gateway
```

Now send a message to the bot from QQ — it should respond!

</details>

<details>
<summary><b>DingTalk (钉钉)</b></summary>

Uses **Stream Mode** — no public IP required.

**1. Create a DingTalk bot**
- Visit [DingTalk Open Platform](https://open-dev.dingtalk.com/)
- Create a new app -> Add **Robot** capability
- **Configuration**:
  - Toggle **Stream Mode** ON
- **Permissions**: Add necessary permissions for sending messages
- Get **AppKey** (Client ID) and **AppSecret** (Client Secret) from "Credentials"
- Publish the app

**2. Configure**

```json
{
  "channels": {
    "dingtalk": {
      "enabled": true,
      "clientId": "YOUR_APP_KEY",
      "clientSecret": "YOUR_APP_SECRET",
      "allowFrom": ["YOUR_STAFF_ID"]
    }
  }
}
```

> `allowFrom`: Add your staff ID. Use `["*"]` to allow all users.

**3. Run**

```bash
velo gateway
```

</details>

<details>
<summary><b>Slack</b></summary>

Uses **Socket Mode** — no public URL required.

**1. Create a Slack app**
- Go to [Slack API](https://api.slack.com/apps) → **Create New App** → "From scratch"
- Pick a name and select your workspace

**2. Configure the app**
- **Socket Mode**: Toggle ON → Generate an **App-Level Token** with `connections:write` scope → copy it (`xapp-...`)
- **OAuth & Permissions**: Add bot scopes: `chat:write`, `reactions:write`, `app_mentions:read`
- **Event Subscriptions**: Toggle ON → Subscribe to bot events: `message.im`, `message.channels`, `app_mention` → Save Changes
- **App Home**: Scroll to **Show Tabs** → Enable **Messages Tab** → Check **"Allow users to send Slash commands and messages from the messages tab"**
- **Install App**: Click **Install to Workspace** → Authorize → copy the **Bot Token** (`xoxb-...`)

**3. Configure velo**

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

**4. Run**

```bash
velo gateway
```

DM the bot directly or @mention it in a channel — it should respond!

> [!TIP]
> - `groupPolicy`: `"mention"` (default — respond only when @mentioned), `"open"` (respond to all channel messages), or `"allowlist"` (restrict to specific channels).
> - DM policy defaults to open. Set `"dm": {"enabled": false}` to disable DMs.

</details>

<details>
<summary><b>Email</b></summary>

Give velo its own email account. It polls **IMAP** for incoming mail and replies via **SMTP** — like a personal email assistant.

**1. Get credentials (Gmail example)**
- Create a dedicated Gmail account for your bot (e.g. `my-velo@gmail.com`)
- Enable 2-Step Verification → Create an [App Password](https://myaccount.google.com/apppasswords)
- Use this app password for both IMAP and SMTP

**2. Configure**

> - `consentGranted` must be `true` to allow mailbox access. This is a safety gate — set `false` to fully disable.
> - `allowFrom`: Add your email address. Use `["*"]` to accept emails from anyone.
> - `smtpUseTls` and `smtpUseSsl` default to `true` / `false` respectively, which is correct for Gmail (port 587 + STARTTLS). No need to set them explicitly.
> - Set `"autoReplyEnabled": false` if you only want to read/analyze emails without sending automatic replies.

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


**3. Run**

```bash
velo gateway
```

</details>

## 🌐 Agent Social Network

🐈 velo is capable of linking to the agent social network (agent community). **Just send one message and your velo joins automatically!**

| Platform | How to Join (send this message to your bot) |
|----------|-------------|
| [**Moltbook**](https://www.moltbook.com/) | `Read https://moltbook.com/skill.md and follow the instructions to join Moltbook` |
| [**ClawdChat**](https://clawdchat.ai/) | `Read https://clawdchat.ai/skill.md and follow the instructions to join ClawdChat` |

Simply send the command above to your velo (via CLI or any chat channel), and it will handle the rest.

## ⚙️ Configuration

Config file: `~/.velo/config.json`

### Providers

> [!TIP]
> - **Groq** provides free voice transcription via Whisper. If configured, Telegram voice messages will be automatically transcribed.
> - **Zhipu Coding Plan**: If you're on Zhipu's coding plan, set `"apiBase": "https://open.bigmodel.cn/api/coding/paas/v4"` in your zhipu provider config.
> - **MiniMax (Mainland China)**: If your API key is from MiniMax's mainland China platform (minimaxi.com), set `"apiBase": "https://api.minimaxi.com/v1"` in your minimax provider config.
> - **VolcEngine Coding Plan**: If you're on VolcEngine's coding plan, set `"apiBase": "https://ark.cn-beijing.volces.com/api/coding/v3"` in your volcengine provider config.
> - **Alibaba Cloud Coding Plan**: If you're on the Alibaba Cloud Coding Plan (BaiLian), set `"apiBase": "https://coding.dashscope.aliyuncs.com/v1"` in your dashscope provider config.

| Provider | Purpose | Get API Key |
|----------|---------|-------------|
| `custom` | Any OpenAI-compatible endpoint (direct, no LiteLLM) | — |
| `openrouter` | LLM (recommended, access to all models) | [openrouter.ai](https://openrouter.ai) |
| `anthropic` | LLM (Claude direct) | [console.anthropic.com](https://console.anthropic.com) |
| `azure_openai` | LLM (Azure OpenAI) | [portal.azure.com](https://portal.azure.com) |
| `openai` | LLM (GPT direct) | [platform.openai.com](https://platform.openai.com) |
| `deepseek` | LLM (DeepSeek direct) | [platform.deepseek.com](https://platform.deepseek.com) |
| `groq` | LLM + **Voice transcription** (Whisper) | [console.groq.com](https://console.groq.com) |
| `gemini` | LLM (Gemini direct) | [aistudio.google.com](https://aistudio.google.com) |
| `minimax` | LLM (MiniMax direct) | [platform.minimaxi.com](https://platform.minimaxi.com) |
| `aihubmix` | LLM (API gateway, access to all models) | [aihubmix.com](https://aihubmix.com) |
| `siliconflow` | LLM (SiliconFlow/硅基流动) | [siliconflow.cn](https://siliconflow.cn) |
| `volcengine` | LLM (VolcEngine/火山引擎) | [volcengine.com](https://www.volcengine.com) |
| `dashscope` | LLM (Qwen) | [dashscope.console.aliyun.com](https://dashscope.console.aliyun.com) |
| `moonshot` | LLM (Moonshot/Kimi) | [platform.moonshot.cn](https://platform.moonshot.cn) |
| `zhipu` | LLM (Zhipu GLM) | [open.bigmodel.cn](https://open.bigmodel.cn) |
| `vllm` | LLM (local, any OpenAI-compatible server) | — |
| `openai_codex` | LLM (Codex, OAuth) | `velo provider login openai-codex` |
| `github_copilot` | LLM (GitHub Copilot, OAuth) | `velo provider login github-copilot` |

<details>
<summary><b>OpenAI Codex (OAuth)</b></summary>

Codex uses OAuth instead of API keys. Requires a ChatGPT Plus or Pro account.

**1. Login:**
```bash
velo provider login openai-codex
```

**2. Set model** (merge into `~/.velo/config.json`):
```json
{
  "agents": {
    "defaults": {
      "model": "openai-codex/gpt-5.1-codex"
    }
  }
}
```

**3. Chat:**
```bash
velo agent -m "Hello!"

# Target a specific workspace/config locally
velo agent -c ~/.velo-telegram/config.json -m "Hello!"

# One-off workspace override on top of that config
velo agent -c ~/.velo-telegram/config.json -w /tmp/velo-telegram-test -m "Hello!"
```

> Docker users: use `docker run -it` for interactive OAuth login.

</details>

<details>
<summary><b>Custom Provider (Any OpenAI-compatible API)</b></summary>

Connects directly to any OpenAI-compatible endpoint — LM Studio, llama.cpp, Together AI, Fireworks, Azure OpenAI, or any self-hosted server. Bypasses LiteLLM; model name is passed as-is.

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

> For local servers that don't require a key, set `apiKey` to any non-empty string (e.g. `"no-key"`).

</details>

<details>
<summary><b>vLLM (local / OpenAI-compatible)</b></summary>

Run your own model with vLLM or any OpenAI-compatible server, then add to config:

**1. Start the server** (example):
```bash
vllm serve meta-llama/Llama-3.1-8B-Instruct --port 8000
```

**2. Add to config** (partial — merge into `~/.velo/config.json`):

*Provider (key can be any non-empty string for local):*
```json
{
  "providers": {
    "vllm": {
      "apiKey": "dummy",
      "apiBase": "http://localhost:8000/v1"
    }
  }
}
```

*Model:*
```json
{
  "agents": {
    "defaults": {
      "model": "meta-llama/Llama-3.1-8B-Instruct"
    }
  }
}
```

</details>

<details>
<summary><b>Adding a New Provider (Developer Guide)</b></summary>

velo uses a **Provider Registry** (`velo/providers/registry.py`) as the single source of truth.
Adding a new provider only takes **2 steps** — no if-elif chains to touch.

**Step 1.** Add a `ProviderSpec` entry to `PROVIDERS` in `velo/providers/registry.py`:

```python
ProviderSpec(
    name="myprovider",                   # config field name
    keywords=("myprovider", "mymodel"),  # model-name keywords for auto-matching
    env_key="MYPROVIDER_API_KEY",        # env var for LiteLLM
    display_name="My Provider",          # shown in `velo status`
    litellm_prefix="myprovider",         # auto-prefix: model → myprovider/model
    skip_prefixes=("myprovider/",),      # don't double-prefix
)
```

**Step 2.** Add a field to `ProvidersConfig` in `velo/config/schema.py`:

```python
class ProvidersConfig(BaseModel):
    ...
    myprovider: ProviderConfig = ProviderConfig()
```

That's it! Environment variables, model prefixing, config matching, and `velo status` display will all work automatically.

**Common `ProviderSpec` options:**

| Field | Description | Example |
|-------|-------------|---------|
| `litellm_prefix` | Auto-prefix model names for LiteLLM | `"dashscope"` → `dashscope/qwen-max` |
| `skip_prefixes` | Don't prefix if model already starts with these | `("dashscope/", "openrouter/")` |
| `env_extras` | Additional env vars to set | `(("ZHIPUAI_API_KEY", "{api_key}"),)` |
| `model_overrides` | Per-model parameter overrides | `(("kimi-k2.5", {"temperature": 1.0}),)` |
| `is_gateway` | Can route any model (like OpenRouter) | `True` |
| `detect_by_key_prefix` | Detect gateway by API key prefix | `"sk-or-"` |
| `detect_by_base_keyword` | Detect gateway by API base URL | `"openrouter"` |
| `strip_model_prefix` | Strip existing prefix before re-prefixing | `True` (for AiHubMix) |

</details>


### MCP (Model Context Protocol)

> [!TIP]
> The config format is compatible with Claude Desktop / Cursor. You can copy MCP server configs directly from any MCP server's README.

velo supports [MCP](https://modelcontextprotocol.io/) — connect external tool servers and use them as native agent tools.

Add MCP servers to your `config.json`:

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
        "headers": {
          "Authorization": "Bearer xxxxx"
        }
      }
    }
  }
}
```

Two transport modes are supported:

| Mode | Config | Example |
|------|--------|---------|
| **Stdio** | `command` + `args` | Local process via `npx` / `uvx` |
| **HTTP** | `url` + `headers` (optional) | Remote endpoint (`https://mcp.example.com/sse`) |

Use `toolTimeout` to override the default 30s per-call timeout for slow servers:

```json
{
  "tools": {
    "mcpServers": {
      "my-slow-server": {
        "url": "https://example.com/mcp/",
        "toolTimeout": 120
      }
    }
  }
}
```

MCP tools are automatically discovered and registered on startup. The LLM can use them alongside built-in tools — no extra configuration needed.




### Security

> [!TIP]
> For production deployments, set `"restrictToWorkspace": true` in your config to sandbox the agent.
> In `v0.1.4.post3` and earlier, an empty `allowFrom` allowed all senders. Since `v0.1.4.post4`, empty `allowFrom` denies all access by default. To allow all senders, set `"allowFrom": ["*"]`.

| Option | Default | Description |
|--------|---------|-------------|
| `tools.restrictToWorkspace` | `false` | When `true`, restricts **all** agent tools (shell, file read/write/edit, list) to the workspace directory. Prevents path traversal and out-of-scope access. |
| `tools.exec.pathAppend` | `""` | Extra directories to append to `PATH` when running shell commands (e.g. `/usr/sbin` for `ufw`). |
| `channels.*.allowFrom` | `[]` (deny all) | Whitelist of user IDs. Empty denies all; use `["*"]` to allow everyone. |


## 🧩 Multiple Instances

Run multiple velo instances simultaneously with separate configs and runtime data. Use `--config` as the main entrypoint, and optionally use `--workspace` to override the workspace for a specific run.

### Quick Start

```bash
# Instance A - Telegram bot
velo gateway --config ~/.velo-telegram/config.json

# Instance B - Discord bot  
velo gateway --config ~/.velo-discord/config.json

# Instance C - Feishu bot with custom port
velo gateway --config ~/.velo-feishu/config.json --port 18792
```

### Path Resolution

When using `--config`, velo derives its runtime data directory from the config file location. The workspace still comes from `agents.defaults.workspace` unless you override it with `--workspace`.

To open a CLI session against one of these instances locally:

```bash
velo agent -c ~/.velo-telegram/config.json -m "Hello from Telegram instance"
velo agent -c ~/.velo-discord/config.json -m "Hello from Discord instance"

# Optional one-off workspace override
velo agent -c ~/.velo-telegram/config.json -w /tmp/velo-telegram-test
```

> `velo agent` starts a local CLI agent using the selected workspace/config. It does not attach to or proxy through an already running `velo gateway` process.

| Component | Resolved From | Example |
|-----------|---------------|---------|
| **Config** | `--config` path | `~/.velo-A/config.json` |
| **Workspace** | `--workspace` or config | `~/.velo-A/workspace/` |
| **Cron Jobs** | config directory | `~/.velo-A/cron/` |
| **Media / runtime state** | config directory | `~/.velo-A/media/` |

### How It Works

- `--config` selects which config file to load
- By default, the workspace comes from `agents.defaults.workspace` in that config
- If you pass `--workspace`, it overrides the workspace from the config file

### Minimal Setup

1. Copy your base config into a new instance directory.
2. Set a different `agents.defaults.workspace` for that instance.
3. Start the instance with `--config`.

Example config:

```json
{
  "agents": {
    "defaults": {
      "workspace": "~/.velo-telegram/workspace",
      "model": "anthropic/claude-sonnet-4-6"
    }
  },
  "channels": {
    "telegram": {
      "enabled": true,
      "token": "YOUR_TELEGRAM_BOT_TOKEN"
    }
  },
  "gateway": {
    "port": 18790
  }
}
```

Start separate instances:

```bash
velo gateway --config ~/.velo-telegram/config.json
velo gateway --config ~/.velo-discord/config.json
```

Override workspace for one-off runs when needed:

```bash
velo gateway --config ~/.velo-telegram/config.json --workspace /tmp/velo-telegram-test
```

### Common Use Cases

- Run separate bots for Telegram, Discord, Feishu, and other platforms
- Keep testing and production instances isolated
- Use different models or providers for different teams
- Serve multiple tenants with separate configs and runtime data

### Notes

- Each instance must use a different port if they run at the same time
- Use a different workspace per instance if you want isolated memory, sessions, and skills
- `--workspace` overrides the workspace defined in the config file
- Cron jobs and runtime media/state are derived from the config directory

## 💻 CLI Reference

| Command | Description |
|---------|-------------|
| `velo onboard` | Initialize config & workspace |
| `velo agent -m "..."` | Chat with the agent |
| `velo agent -w <workspace>` | Chat against a specific workspace |
| `velo agent -w <workspace> -c <config>` | Chat against a specific workspace/config |
| `velo agent` | Interactive chat mode |
| `velo agent --no-markdown` | Show plain-text replies |
| `velo agent --logs` | Show runtime logs during chat |
| `velo gateway` | Start the gateway |
| `velo status` | Show status |
| `velo provider login openai-codex` | OAuth login for providers |
| `velo channels login` | Link WhatsApp (scan QR) |
| `velo channels status` | Show channel status |

Interactive mode exits: `exit`, `quit`, `/exit`, `/quit`, `:q`, or `Ctrl+D`.

<details>
<summary><b>Heartbeat (Periodic Tasks)</b></summary>

The gateway wakes up every 30 minutes and checks `HEARTBEAT.md` in your workspace (`~/.velo/workspace/HEARTBEAT.md`). If the file has tasks, the agent executes them and delivers results to your most recently active chat channel.

**Setup:** edit `~/.velo/workspace/HEARTBEAT.md` (created automatically by `velo onboard`):

```markdown
## Periodic Tasks

- [ ] Check weather forecast and send a summary
- [ ] Scan inbox for urgent emails
```

The agent can also manage this file itself — ask it to "add a periodic task" and it will update `HEARTBEAT.md` for you.

> **Note:** The gateway must be running (`velo gateway`) and you must have chatted with the bot at least once so it knows which channel to deliver to.

</details>

## 🐳 Docker

> [!TIP]
> The `-v ~/.velo:/root/.velo` flag mounts your local config directory into the container, so your config and workspace persist across container restarts.

### Docker Compose

```bash
docker compose run --rm velo-cli onboard   # first-time setup
vim ~/.velo/config.json                     # add API keys
docker compose up -d velo-gateway           # start gateway
```

```bash
docker compose run --rm velo-cli agent -m "Hello!"   # run CLI
docker compose logs -f velo-gateway                   # view logs
docker compose down                                      # stop
```

### Docker

```bash
# Build the image
docker build -t velo .

# Initialize config (first time only)
docker run -v ~/.velo:/root/.velo --rm velo onboard

# Edit config on host to add API keys
vim ~/.velo/config.json

# Run gateway (connects to enabled channels, e.g. Telegram/Discord/Mochat)
docker run -v ~/.velo:/root/.velo -p 18790:18790 velo gateway

# Or run a single command
docker run -v ~/.velo:/root/.velo --rm velo agent -m "Hello!"
docker run -v ~/.velo:/root/.velo --rm velo status
```

## 🐧 Linux Service

Run the gateway as a systemd user service so it starts automatically and restarts on failure.

**1. Find the velo binary path:**

```bash
which velo   # e.g. /home/user/.local/bin/velo
```

**2. Create the service file** at `~/.config/systemd/user/velo-gateway.service` (replace `ExecStart` path if needed):

```ini
[Unit]
Description=Nanobot Gateway
After=network.target

[Service]
Type=simple
ExecStart=%h/.local/bin/velo gateway
Restart=always
RestartSec=10
NoNewPrivileges=yes
ProtectSystem=strict
ReadWritePaths=%h

[Install]
WantedBy=default.target
```

**3. Enable and start:**

```bash
systemctl --user daemon-reload
systemctl --user enable --now velo-gateway
```

**Common operations:**

```bash
systemctl --user status velo-gateway        # check status
systemctl --user restart velo-gateway       # restart after config changes
journalctl --user -u velo-gateway -f        # follow logs
```

If you edit the `.service` file itself, run `systemctl --user daemon-reload` before restarting.

> **Note:** User services only run while you are logged in. To keep the gateway running after logout, enable lingering:
>
> ```bash
> loginctl enable-linger $USER
> ```

## 📁 Project Structure

```
velo/
├── agent/          # 🧠 Core agent logic
│   ├── loop.py     #    Agent loop (LLM ↔ tool execution)
│   ├── context.py  #    Prompt builder
│   ├── memory.py   #    Persistent memory
│   ├── skills.py   #    Skills loader
│   ├── subagent.py #    Background task execution
│   └── tools/      #    Built-in tools (incl. spawn)
├── skills/         # 🎯 Bundled skills (github, weather, tmux...)
├── channels/       # 📱 Chat channel integrations
├── bus/            # 🚌 Message routing
├── cron/           # ⏰ Scheduled tasks
├── heartbeat/      # 💓 Proactive wake-up
├── providers/      # 🤖 LLM providers (OpenRouter, etc.)
├── session/        # 💬 Conversation sessions
├── config/         # ⚙️ Configuration
└── cli/            # 🖥️ Commands
```

## 🤝 Contribute & Roadmap

PRs welcome! The codebase is intentionally small and readable. 🤗

**Roadmap** — Pick an item and [open a PR](https://github.com/HKUDS/velo/pulls)!

- [ ] **Multi-modal** — See and hear (images, voice, video)
- [ ] **Long-term memory** — Never forget important context
- [ ] **Better reasoning** — Multi-step planning and reflection
- [ ] **More integrations** — Calendar and more
- [ ] **Self-improvement** — Learn from feedback and mistakes

### Contributors

<a href="https://github.com/HKUDS/velo/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=HKUDS/velo&max=100&columns=12&updated=20260210" alt="Contributors" />
</a>


## ⭐ Star History

<div align="center">
  <a href="https://star-history.com/#HKUDS/velo&Date">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=HKUDS/velo&type=Date&theme=dark" />
      <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=HKUDS/velo&type=Date" />
      <img alt="Star History Chart" src="https://api.star-history.com/svg?repos=HKUDS/velo&type=Date" style="border-radius: 15px; box-shadow: 0 0 30px rgba(0, 217, 255, 0.3);" />
    </picture>
  </a>
</div>

<p align="center">
  <em> Thanks for visiting ✨ velo!</em><br><br>
  <img src="https://visitor-badge.laobi.icu/badge?page_id=HKUDS.velo&style=for-the-badge&color=00d4ff" alt="Views">
</p>


<p align="center">
  <sub>velo is for educational, research, and technical exchange purposes only</sub>
</p>
