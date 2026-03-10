# MCP Servers Reference

This reference lists MCP servers that work well with nanobot agents, along with
installation notes and config snippets.

---

## Available MCP Servers

| Service | Package | Notes |
|---------|---------|-------|
| **Shopify Admin** | `@shopify/dev-mcp` | Get token via private app (recommended), not OAuth — see `library/integration-recipes/shopify.md` |
| **GitHub** | `@modelcontextprotocol/server-github` | Requires `GITHUB_TOKEN` env var |
| **Filesystem** | `@modelcontextprotocol/server-filesystem` | Restrict paths via `allowedDirectories` config |
| **Postgres** | `@modelcontextprotocol/server-postgres` | Pass `DATABASE_URL` in env |
| **Brave Search** | `@modelcontextprotocol/server-brave-search` | Requires `BRAVE_API_KEY` |
| **Slack** | `@modelcontextprotocol/server-slack` | Requires `SLACK_BOT_TOKEN` and `SLACK_TEAM_ID` |
| **Google Drive** | `@modelcontextprotocol/server-gdrive` | OAuth2 credentials via `GDRIVE_CREDENTIALS_FILE` |
| **Notion** | `@notionhq/mcp-server` | Requires `NOTION_TOKEN` |
| **Linear** | `@linear/mcp-server` | Requires `LINEAR_API_KEY` |

---

## Adding an MCP Server

MCP servers are configured in the workspace `.mcp.json` or in `AGENTS.md`.

### `.mcp.json` format

```json
{
  "mcpServers": {
    "github": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": {
        "GITHUB_TOKEN": "${GITHUB_TOKEN}"
      }
    }
  }
}
```

### AGENTS.md format

In `AGENTS.md` you can reference the same `.mcp.json` file or inline the config
under a `mcp_servers` frontmatter block.

---

## Tips

- **Least privilege:** Only grant the scopes your agent actually needs.
- **Env vars:** Always pass secrets via environment variables, never hardcode
  them in config files.
- **Timeouts:** Set `timeout` in the MCP server config if the service is slow
  to respond.
- **Multiple stores/accounts:** Create one MCP server entry per account, using
  distinct keys (e.g. `shopify_store_a`, `shopify_store_b`).
