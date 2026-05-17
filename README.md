# Infinite Money Glitch

AI-powered grant-finding agent for artists, community organizers, dancers, poets, curators, and nonprofits. Searches Grants.gov, NYFA Source, Unrestricted Funds, and SerpAPI — scores each grant for eligibility and fit, sends a daily digest email, and lets you draft Letters of Intent on demand.

## Structure

```
agent/    # Python pipeline (Flask + Cloud Run)
web/      # Next.js frontend (Firebase Auth + dashboard)
```

## Stack

- **Agent**: Python, Flask, Claude API (Haiku scoring + Sonnet LOI generation), Cloud Run
- **Web**: Next.js 16, TypeScript, Tailwind CSS, Firebase Auth
- **DB**: Cloud SQL (Postgres)
- **Grant sources**: Grants.gov REST API, SerpAPI, NYFA Source, Unrestricted Funds, Serper.dev

## See CLAUDE.md for full architecture, deploy checklist, and local dev setup.
