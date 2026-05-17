# Readymade.hire (SaaS)

AI-powered job application agent. Multi-user platform built on the Readymade.hire engine.

## Structure

```
agent/    # Python pipeline (Flask + Cloud Run)
web/      # Next.js frontend (coming soon)
```

## Stack

- **Agent**: Python, Flask, Claude API (Haiku + Sonnet), Cloud Run
- **Web**: Next.js, Firebase Auth
- **DB**: Cloud SQL (Postgres)
- **CI/CD**: Cloud Build → Cloud Run
