---
name: himalaya
description: |
  CLI email client for any IMAP/SMTP provider (Gmail, Outlook, ProtonMail, self-hosted).
  Use when the user asks about email and they don't use Google Workspace, or when
  himalaya is configured as their email provider. Supports list, read, send, reply,
  forward, search, attachments, and folder management.
metadata:
  requires:
    bins: ["himalaya"]
---

# Himalaya Email CLI

Himalaya is a CLI email client that manages emails via IMAP/SMTP from the terminal. Works with any email provider.

## When to Use

- User asks about email and doesn't have Google Workspace configured
- User explicitly uses Outlook, ProtonMail, or another non-Google provider
- Himalaya binary is available (`himalaya --version`)

## Common Commands

| Action | Command |
|--------|---------|
| List inbox | `himalaya envelope list --folder INBOX --page-size 10` |
| List with JSON output | `himalaya envelope list --output json` |
| Search by sender | `himalaya envelope list from boss@company.com` |
| Search by subject | `himalaya envelope list subject "quarterly report"` |
| Combined search | `himalaya envelope list from alice@example.com subject meeting` |
| Read message | `himalaya message read <id>` |
| Reply | `himalaya message reply <id>` |
| Reply-all | `himalaya message reply <id> --all` |
| Forward | `himalaya message forward <id>` |
| Move to folder | `himalaya message move <id> "Archive"` |
| Copy to folder | `himalaya message copy <id> "Important"` |
| Delete | `himalaya message delete <id>` |
| List folders | `himalaya folder list` |
| Download attachments | `himalaya attachment download <id>` |

## Sending Emails Non-Interactively

For agent use (no $EDITOR), pipe MML content to `himalaya template send`:

```bash
cat << 'EOF' | himalaya template send
From: user@example.com
To: recipient@example.com
Subject: Meeting follow-up

Hi, just following up on our meeting earlier today.

Best regards
EOF
```

## JSON Output Parsing

Always use `--output json` when you need structured data:

```bash
himalaya envelope list --folder INBOX --page-size 5 --output json
```

Returns a JSON array of envelope objects with `id`, `from`, `subject`, `date` fields.

## Tips

- Message IDs are relative to the current folder — re-list after switching folders
- Use `himalaya --help` or `himalaya <command> --help` for detailed usage
- For rich emails with attachments, use MML syntax (see `references/setup.md`)
- Passwords are retrieved via command (`backend.auth.cmd`) — never stored in config directly

## Setup

See `references/setup.md` for installation and provider configuration (Gmail, Outlook, generic IMAP).
