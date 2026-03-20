#!/bin/bash
set -e

TOKEN_FILE="/run/secrets/tenant_token"
CONFIG="$HOME/.velo/config.json"

if [ -f "$TOKEN_FILE" ] && [ -f "$CONFIG" ]; then
    TOKEN="$(cat "$TOKEN_FILE")"

    # Export tenant token as env vars for all proxy services.
    # Each proxy client reads its own env var for authentication.
    export COMPOSIO_API_KEY="$TOKEN"

    # Inject token into config.json paths (LLM, dashboard, honcho, parallel).
    # Write target is the volume mount, which bypasses read_only: true.
    TOKEN="$TOKEN" python3 -c "
import json, os

config_path = os.path.join(os.environ.get('HOME', '/root'), '.velo', 'config.json')
with open(config_path) as f:
    c = json.load(f)

token = os.environ['TOKEN']

# Inject into all config paths that use the tenant token
if 'providers' in c and 'anthropic' in c.get('providers', {}):
    c['providers']['anthropic']['apiKey'] = token
if 'channels' in c and 'dashboard' in c.get('channels', {}):
    c['channels']['dashboard']['supabaseKey'] = token
if 'honcho' in c:
    c['honcho']['apiKey'] = token
if 'tools' in c and 'web' in c.get('tools', {}) and 'search' in c['tools'].get('web', {}):
    c['tools']['web']['search']['apiKey'] = token

with open(config_path, 'w') as f:
    json.dump(c, f, indent=2)
"
fi

exec velo "$@"
