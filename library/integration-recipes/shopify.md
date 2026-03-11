# Shopify Integration Recipe

This recipe shows how to connect a velo agent to a Shopify store using the
Shopify Admin API MCP server and the webhook-receiver plugin.

---

## Prerequisites

- A Shopify store (development store is fine)
- A Shopify Admin API access token (see below)
- `velo` with the `webhook-receiver` plugin

---

## Step 1: Get an Admin API Token

### Method 1: Private App Token (Recommended for VPS agents)

1. Go to Shopify Admin → **Settings** → **Apps** → **Develop apps**
2. Click **Enable custom apps** if prompted
3. Click **Create an app**, give it a name (e.g. "velo")
4. Go to **Configure Admin API access** and select the scopes you need:
   - Order support: `read_orders`, `read_customers`, `read_fulfillments`
   - Order management: add `write_orders`
   - Inventory: `read_inventory`, `write_inventory`
   - Products: `read_products`, `write_products`
5. Click **Install app**
6. Copy the **Admin API access token** — it is shown only once

This token does not expire and is scoped to one store. Store it in your `.env`:

```
SHOPIFY_ADMIN_TOKEN=shpat_xxxxxxxxxxxxxxxxxxxx
SHOPIFY_STORE_DOMAIN=your-store.myshopify.com
```

### Method 2: OAuth Flow (not needed for Volos)

OAuth is designed for public Shopify apps distributed via the App Store that
need to connect to many different stores. For a single-store VPS agent,
Method 1 is simpler and more appropriate.

If OAuth is required:

1. Register a custom app in the Shopify Partner Dashboard to get a client ID
   and client secret
2. Direct the merchant to the OAuth authorize URL:
   ```
   https://{shop}.myshopify.com/admin/oauth/authorize
     ?client_id={client_id}
     &scope={comma_separated_scopes}
     &redirect_uri={your_callback_url}
     &state={nonce}
   ```
3. Shopify redirects back to `redirect_uri` with an `?code=` parameter
4. Exchange the code for a permanent access token:
   ```http
   POST https://{shop}.myshopify.com/admin/oauth/access_token
   Content-Type: application/json

   {
     "client_id": "{client_id}",
     "client_secret": "{client_secret}",
     "code": "{authorization_code}"
   }
   ```
5. Store the returned `access_token` — it does not expire

---

## Step 2: Configure the MCP Server

Add the Shopify Admin MCP server to your workspace `AGENTS.md` or `.mcp.json`:

```json
{
  "mcpServers": {
    "shopify": {
      "command": "npx",
      "args": ["-y", "@shopify/dev-mcp@latest"],
      "env": {
        "SHOPIFY_ACCESS_TOKEN": "${SHOPIFY_ADMIN_TOKEN}",
        "MYSHOPIFY_DOMAIN": "${SHOPIFY_STORE_DOMAIN}"
      }
    }
  }
}
```

---

## Step 3: Receive Webhooks (optional)

Enable the `webhook-receiver` plugin to react to Shopify events in real time.

In `config.yml`:

```yaml
plugins:
  webhook-receiver:
    enabled: true
    port: 8090
    routes:
      - path: /webhooks/shopify/orders
        service: shopify
        secret_env: SHOPIFY_CLIENT_SECRET
      - path: /webhooks/shopify/inventory
        service: shopify
        secret_env: SHOPIFY_CLIENT_SECRET
    reject_invalid_signatures: true
```

In Shopify Admin → Settings → Notifications → Webhooks, add:

- **Orders/created** → `https://your-vps.example.com:8090/webhooks/shopify/orders`
- **Inventory items/updated** → `https://your-vps.example.com:8090/webhooks/shopify/inventory`

Set the **Signing secret** (your app's API secret key) as `SHOPIFY_CLIENT_SECRET`
in your `.env`. Note: Shopify uses the **app's client secret** for all webhook
signatures, not a per-endpoint secret.

---

## Using Both Together

With both the MCP server and webhook-receiver active, the agent can:

- **React to events** — new order webhook triggers the agent, which queries
  order details via the MCP tool and sends a Telegram notification
- **Manage inventory** — agent polls low-stock products via MCP and reorders
- **Answer questions** — "How many orders came in today?" queries via MCP

Example system prompt addition (in `SOUL.md`):

```markdown
You are connected to a Shopify store. When you receive a webhook notification
about a new order, check the order details and notify the owner via Telegram.
Keep a running summary of today's orders and revenue.
```

---

## Available Tools (via MCP)

The Shopify Admin MCP server exposes tools including:

| Tool | Description |
|------|-------------|
| `get_order` | Retrieve a single order by ID |
| `list_orders` | List orders with filters |
| `get_product` | Get product details |
| `update_inventory` | Adjust inventory levels |
| `create_fulfillment` | Fulfill an order |

Exact tool names depend on the MCP server version. Run `list_tools` in the
agent to see what is available.

---

## Troubleshooting

**Webhook signature failures:** Ensure `SHOPIFY_CLIENT_SECRET` contains the
app's API secret key (not the Admin API access token). The secret is found in
the custom app settings under "API credentials".

**401 errors from Admin API:** Check that the access token has the required
scopes for the operations you are attempting.

**MCP server not found:** Run `npx @shopify/dev-mcp --version` to verify the
package is accessible from the VPS.
