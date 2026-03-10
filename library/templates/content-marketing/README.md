# Content Marketing Agent Template

An AI content marketing strategist powered by the `coreyhaines31/marketingskills` skill pack.

## Required Skills

Install the following skills before using this template:

```bash
npx skills add coreyhaines31/marketingskills \
  --skill product-marketing-context copywriting content-strategy \
  social-content email-sequence
```

**Required:** `product-marketing-context`, `copywriting`

**Recommended:** `content-strategy`, `social-content`, `email-sequence`, `seo-audit`,
`marketing-ideas`, `competitor-alternatives`

## Setup

1. **Fill in SOUL.md** — replace the `{{placeholder}}` values:
   - `{{brand_name}}` — your company or product name
   - `{{brand_voice}}` — e.g. "professional but approachable, no jargon"
   - `{{target_audience}}` — e.g. "B2B SaaS founders, 25–45"
   - `{{primary_channels}}` — e.g. "LinkedIn, email newsletter, blog"
   - `{{content_pillars}}` — e.g. "product updates, industry insights, customer stories"

2. **Optional: knowledge base** — point `doc_directory` in `config.yml` at your brand
   guidelines folder (accepts `.md`, `.txt`, `.pdf`). The agent will index it on startup.

3. **Deploy the plugins** listed in `config.yml`:
   ```
   cp -r library/plugins/horizontal/knowledge-base {workspace}/plugins/
   cp -r library/plugins/horizontal/conversation-analytics {workspace}/plugins/
   ```

## Usage

Once configured, the agent can:
- Draft blog posts, social content, and email sequences using your brand voice
- Plan a content calendar and track topics in memory
- Research competitor positioning and suggest differentiation angles
- Audit existing content for SEO gaps
- Brainstorm campaign ideas aligned with your content pillars
