# Himalaya Setup Guide

## Installation (Linux VPS)

```bash
curl -sSL https://raw.githubusercontent.com/pimalaya/himalaya/master/install.sh | sudo sh
```

Verify: `himalaya --version` (should show v1.2.0+)

## Configuration

Config file location: `~/.config/himalaya/config.toml`

### Gmail (App Password)

Prerequisites:
- IMAP enabled in Gmail settings
- 2-step authentication enabled
- App Password generated at https://myaccount.google.com/apppasswords

```toml
[accounts.default]
email = "user@gmail.com"

folder.aliases.inbox = "INBOX"
folder.aliases.sent = "[Gmail]/Sent Mail"
folder.aliases.drafts = "[Gmail]/Drafts"
folder.aliases.trash = "[Gmail]/Trash"

backend.type = "imap"
backend.host = "imap.gmail.com"
backend.port = 993
backend.login = "user@gmail.com"
backend.auth.type = "password"
backend.auth.cmd = "cat /root/.velo/secrets/email_password"

message.send.backend.type = "smtp"
message.send.backend.host = "smtp.gmail.com"
message.send.backend.port = 465
message.send.backend.login = "user@gmail.com"
message.send.backend.auth.type = "password"
message.send.backend.auth.cmd = "cat /root/.velo/secrets/email_password"
```

### Outlook

```toml
[accounts.default]
email = "user@outlook.com"

backend.type = "imap"
backend.host = "outlook.office365.com"
backend.port = 993
backend.login = "user@outlook.com"
backend.auth.type = "password"
backend.auth.cmd = "cat /root/.velo/secrets/email_password"

message.send.backend.type = "smtp"
message.send.backend.host = "smtp-mail.outlook.com"
message.send.backend.port = 587
message.send.backend.encryption.type = "start-tls"
message.send.backend.login = "user@outlook.com"
message.send.backend.auth.type = "password"
message.send.backend.auth.cmd = "cat /root/.velo/secrets/email_password"
```

### Generic IMAP (Any Provider)

```toml
[accounts.default]
email = "user@example.com"

backend.type = "imap"
backend.host = "mail.example.com"
backend.port = 993
backend.login = "user@example.com"
backend.auth.type = "password"
backend.auth.cmd = "cat /root/.velo/secrets/email_password"

message.send.backend.type = "smtp"
message.send.backend.host = "mail.example.com"
message.send.backend.port = 465
message.send.backend.login = "user@example.com"
message.send.backend.auth.type = "password"
message.send.backend.auth.cmd = "cat /root/.velo/secrets/email_password"
```

## Security

- Store passwords in `/root/.velo/secrets/email_password` (readable only by root)
- Retrieved via `backend.auth.cmd = "cat /root/.velo/secrets/email_password"`
- Never store passwords directly in the TOML config file
- For Gmail: use an App Password, not your regular Google password

## Verification

After setup, verify the connection works:

```bash
himalaya envelope list --page-size 1
```

If it returns an email envelope, the setup is working correctly.
