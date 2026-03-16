---
name: competitor-monitor
description: |
  Monitor competitor websites, pricing, product launches, and hiring patterns.
  Use when the user asks to track competitors, or as a recurring heartbeat task.
  Uses web search to check for changes — no special integrations needed.
metadata: {}
---

# Competitor Monitor

Track competitor activity using web search and store findings in workspace/competitor-notes.md.

## When to Use

- User asks to "track competitors", "monitor competition", "watch what X is doing"
- As a recurring heartbeat task (add to HEARTBEAT.md)
- Before strategy meetings or quarterly planning

## What to Monitor

| Category | What to Check | How |
|----------|--------------|-----|
| Pricing | Price changes, new tiers, feature gating | Search "[competitor] pricing" monthly |
| Product | New features, launches, changelog updates | Search "[competitor] changelog OR release notes" |
| Hiring | New roles, team growth, strategic hires | Search "[competitor] careers OR jobs" |
| Content | Blog posts, case studies, thought leadership | Search "[competitor] blog" |
| Social | Twitter/LinkedIn activity, announcements | Search "site:twitter.com [competitor]" |

## How to Store Findings

Append to `workspace/competitor-notes.md`:

```
## 2026-03-16 — Acme Corp — Pricing Change
Raised Pro tier from $49 to $59/mo. Enterprise tier unchanged.
Source: https://acme.com/pricing

## 2026-03-14 — Acme Corp — New Feature
Launched AI-powered analytics dashboard.
Source: https://acme.com/blog/analytics-launch
```

## When to Alert the User

Alert immediately for:
- Significant pricing changes (>10% increase/decrease)
- New product launches or major feature announcements
- Hiring surges (5+ new roles in a week — signals strategic shift)

Don't alert for:
- Routine blog posts
- Minor website copy changes
- Job postings for backfills

## Heartbeat Integration

Add to HEARTBEAT.md for automated monitoring:
```
Check competitors weekly: search for pricing changes, new features, and hiring activity for [competitor list]. Save findings to competitor-notes.md. Alert only on significant changes.
```
