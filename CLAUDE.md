# CLAUDE.md

This file provides guidance to Claude Code when working in this repository.

## What This Project Is

**Infinite Money Glitch** is a grant-finding agent for artists, community organizers, dancers, poets, curators, nonprofits, and collectives. It searches multiple grant sources, scores each grant for eligibility and fit using Claude, sends a daily digest email, and lets users draft Letters of Intent (LOI) or artist statements on demand from the dashboard.

It is a fork of `readymadehire.saas` (job-finding SaaS). ~70% of the infrastructure carries over unchanged. The key differences: grant sources instead of job boards, eligibility-first scoring, on-demand document drafting (not auto-generated), and an artist-specific onboarding profile.

## Current Status — **SCAFFOLD COMPLETE, NOT YET DEPLOYED**

The full codebase is built and verified offline (`--mock --dry-run` passes). The next task is deploy.

---

## ⚡ Deploy Checklist — Start Here

When opening this repo, the goal is to get this live. Work through these in order.

### Step 1 — Firebase (Ibrahim does this manually)
1. Go to [Firebase Console](https://console.firebase.google.com) → Create new project → name it something like `infinite-money-glitch`
2. In the new project: **Authentication → Sign-in method → Google → Enable**
3. Add your production domain (Vercel URL) to **Authentication → Settings → Authorized domains** once you have it
4. Go to **Project Settings → Service accounts → Generate new private key** → download the JSON
5. In GCP Console → **Secret Manager** → Create secret named `imf-firebase-service-account` → paste the full JSON content as the value
6. Grant the Cloud Run service account access to that secret (same pattern as readymadehire)

### Step 2 — Database (run once)
Connect to the existing Cloud SQL instance (`readymadehire-db`, project `stalwart-edge-453119-m6`):
```sql
CREATE DATABASE infinitemoneyglitch;
```
The `init_db()` function in `grant_store.py` creates all tables automatically on first server startup. No manual schema setup needed.

### Step 3 — Deploy Agent to Cloud Run
```bash
cd agent
gcloud run deploy infinitemoneyglitch-agent \
  --source . \
  --project stalwart-edge-453119-m6 \
  --region us-central1 \
  --platform managed \
  --allow-unauthenticated \
  --add-cloudsql-instances stalwart-edge-453119-m6:us-central1:readymadehire-db \
  --set-env-vars "
    ANTHROPIC_API_KEY=<key>,
    SERPAPI_API_KEY=<key>,
    SERPER_API_KEY=<key>,
    RESEND_API_KEY=<key>,
    SENDER_EMAIL=Infinite Money Glitch <noreply@gugul.xyz>,
    DATABASE_URL=postgresql://postgres:<password>@/infinitemoneyglitch?host=/cloudsql/stalwart-edge-453119-m6:us-central1:readymadehire-db
  " \
  --set-secrets "FIREBASE_SERVICE_ACCOUNT=imf-firebase-service-account:latest"
```
Note the `DATABASE_URL` format — Unix socket path for Cloud SQL Auth Proxy (no IP allowlisting needed).

### Step 4 — Deploy Web to Vercel
1. Go to [Vercel](https://vercel.com) → New Project → Import `Ctrl-Alt-Cr8/infinitemoneyglitch`
2. Set **Root Directory** to `web`
3. Add these environment variables (from the new Firebase project's Project Settings → General):
```
NEXT_PUBLIC_FIREBASE_API_KEY=
NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN=
NEXT_PUBLIC_FIREBASE_PROJECT_ID=
NEXT_PUBLIC_FIREBASE_STORAGE_BUCKET=
NEXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID=
NEXT_PUBLIC_FIREBASE_APP_ID=
NEXT_PUBLIC_FIREBASE_MEASUREMENT_ID=
NEXT_PUBLIC_AGENT_URL=<Cloud Run URL from Step 3>
```
4. Deploy. Copy the production URL → add it to Firebase Authorized Domains (Step 1.3).

### Step 5 — End-to-End Test
```
1. Open Vercel URL → sign in with Google
2. Complete onboarding: select disciplines, org type, geographic focus, scoring priorities
3. Dashboard → Find Grants → wait ~2 min → refresh
4. Verify grants appear with PRIORITY/REVIEW/SKIP badges
5. Click Draft on a PRIORITY grant → select LOI → verify document generates and saves to Drafts tab
6. Check digest email arrived at the recipient address from onboarding
```

---

## Repo Structure

```
agent/    # Python pipeline — Flask server, Claude API, grant scoring, LOI generation
web/      # Next.js frontend — Firebase Auth, onboarding, dashboard
```

## Stack

- **Agent**: Python, Flask, Cloud Run (GCP)
- **AI**: Claude Haiku (scoring) + Claude Sonnet (LOI/artist statement) via Anthropic API
- **DB**: Cloud SQL (Postgres) on existing `readymadehire-db` instance, database `infinitemoneyglitch`
- **Auth**: Firebase Auth (ID token verified on agent, Firebase SDK on web)
- **Web**: Next.js 16, TypeScript, Tailwind CSS
- **CI/CD**: `gcloud run deploy --source .` (agent), Vercel (web)
- **Grant sources**: Grants.gov REST API (free), SerpAPI grant queries, NYFA Source scraper, Unrestricted Funds scraper, Serper.dev fallback

## Agent Architecture & Data Flow

The pipeline in `agent/app/main.py` runs in order:

1. **Load config** (`storage/grant_store.py → get_user_config(user_id)`): Loads `UserConfig` from Postgres. Falls back to `config.py` if no `DATABASE_URL` (local testing).
2. **Fetch** (`sources/fetcher_router.py → fetch_all_grants(user_config)`): Runs all grant sources in sequence, deduplicates by title+funder.
   - Grants.gov REST API (federal grants, free, no key)
   - SerpAPI — keyword + discipline queries (e.g. `"visual art grants NYC 2026 open applications"`)
   - Serper.dev fallback if SerpAPI empty
   - NYFA Source scraper (`nyfa.org/opportunities`)
   - Unrestricted Funds scraper (`unrestrictedfunds.com`)
3. **Disqualify** (`scoring/filters.py → disqualify_grants()`): Hard-blocks expired deadlines, confirmed org type mismatches.
4. **Filter** (`scoring/filters.py → passes_filters()`): Discipline relevance + geographic compatibility. All location logic lives here.
5. **Memory filter** (`storage/grant_store.py → is_known_grant()`): Skips grants already seen by this user. Checks by `user_id + title + funder`.
6. **Eligibility map**: Pre-compute `eligible/likely/unclear/ineligible` for each grant based on org type.
7. **Score** (`scoring/scorer.py → score_grants_batch(grants, profile, eligibility_map)`): Batches 8 grants per Claude Haiku call. Eligibility gates the score (ineligible → 0–15 regardless of fit). User's scoring weights (High/Med/Low for mission/award/deadline) influence the rest.
8. **Decide**: Top 20 scored grants. Score ≥ 85 → **PRIORITY**; 70–84 → **REVIEW**; < 70 → **SKIP**.
9. **Email digest** (`utils/send_email.py`): PRIORITY + REVIEW sections. No documents attached — drafting is on-demand from dashboard.
10. **Record** (`storage/grant_store.py → record_grant()`): All grants written to Postgres with `user_id`, decision, score.
11. **Cost log** (`storage/grant_store.py → record_run_log()`): Token counts + estimated cost written to `run_logs`.

**LOI / Artist Statement** — NOT part of the pipeline. Generated on-demand only:
- `POST /draft-document` endpoint → `composer/loi_generator.py → generate_loi()` or `generate_artist_statement()`
- Two-pass Claude Sonnet: generate → validate → retry once if needed
- Saved to `drafts` table, returned to dashboard immediately

## Database Schema

All tables created by `init_db()` on first server startup (advisory-locked, gunicorn-safe).

```sql
-- One row per registered user (Firebase UID as primary key)
CREATE TABLE users (
    id         TEXT PRIMARY KEY,
    email      TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Per-user artist profile and pipeline config
CREATE TABLE user_configs (
    user_id              TEXT PRIMARY KEY REFERENCES users(id),
    name                 TEXT NOT NULL,
    disciplines          TEXT[],          -- ["visual art", "community organizing"]
    org_type             TEXT,            -- "individual" | "collective" | "nonprofit"
    location_pref        TEXT,
    geographic_focus     TEXT[],          -- ["NYC", "New York State", "national"]
    keywords             TEXT[],
    summary              TEXT,
    constraints          TEXT,
    recipient_email      TEXT,
    project_description  TEXT,
    past_grants          TEXT,
    budget_min           INTEGER DEFAULT 0,
    deadline_window_days INTEGER DEFAULT 90,
    scoring_weights      JSONB,           -- {"mission": "high", "award": "medium", "deadline": "medium"}
    interview_answers    TEXT,
    updated_at           TIMESTAMPTZ DEFAULT NOW()
);

-- All grants seen and processed per user
CREATE TABLE grants (
    id           SERIAL PRIMARY KEY,
    user_id      TEXT NOT NULL,
    title        TEXT NOT NULL,
    funder       TEXT NOT NULL,
    url          TEXT,
    award_amount TEXT,
    deadline     TEXT,         -- ISO date "2026-08-15" or "Rolling"
    eligibility  TEXT,
    disciplines  TEXT[],
    org_types    TEXT[],
    location     TEXT,
    description  TEXT,
    source       TEXT,
    first_seen   DATE NOT NULL,
    last_seen    DATE NOT NULL,
    decision     TEXT,         -- "PRIORITY" | "REVIEW" | "SKIP"
    email_sent   BOOLEAN DEFAULT FALSE,
    score        INTEGER DEFAULT 0
);

-- Per-run cost and summary log
CREATE TABLE run_logs (
    id               SERIAL PRIMARY KEY,
    user_id          TEXT NOT NULL REFERENCES users(id),
    run_at           TIMESTAMPTZ DEFAULT NOW(),
    grants_fetched   INTEGER,
    grants_priority  INTEGER,
    grants_review    INTEGER,
    grants_skip      INTEGER,
    haiku_tokens     INTEGER,
    sonnet_tokens    INTEGER,
    estimated_cost   NUMERIC(8, 4)
);

-- On-demand LOI and artist statement drafts
CREATE TABLE drafts (
    id         SERIAL PRIMARY KEY,
    user_id    TEXT NOT NULL REFERENCES users(id),
    grant_id   INTEGER REFERENCES grants(id),
    doc_type   TEXT NOT NULL,    -- "loi" | "artist_statement"
    content    TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

## Environment Variables

### `agent/.env` (local) / Cloud Run env vars (production)

```
# Anthropic
ANTHROPIC_API_KEY=

# Grant sources
SERPAPI_API_KEY=
SERPER_API_KEY=

# Email (Resend)
RESEND_API_KEY=
SENDER_EMAIL=Infinite Money Glitch <noreply@gugul.xyz>

# Database
# Leave blank for --mock --dry-run offline testing
# DATABASE_URL=postgresql://postgres:<password>@/infinitemoneyglitch?host=/cloudsql/<instance>

# Firebase Admin SDK (path locally, full JSON string on Cloud Run)
FIREBASE_SERVICE_ACCOUNT=firebase-service-account.json

# CLI-only (used for --mock / --dry-run; server uses Firebase UID)
USER_ID=default
RECIPIENT_EMAIL=
```

### `web/.env.local` (local) / Vercel env vars (production)

```
NEXT_PUBLIC_FIREBASE_API_KEY=
NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN=
NEXT_PUBLIC_FIREBASE_PROJECT_ID=
NEXT_PUBLIC_FIREBASE_STORAGE_BUCKET=
NEXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID=
NEXT_PUBLIC_FIREBASE_APP_ID=
NEXT_PUBLIC_FIREBASE_MEASUREMENT_ID=
NEXT_PUBLIC_AGENT_URL=http://localhost:8080  # update to Cloud Run URL after deploy
```

## Claude Model Usage

- **Claude Haiku** (`claude-haiku-4-5-20251001`): Grant scoring — cheap, batch-optimized (8 grants per call)
- **Claude Sonnet** (`claude-sonnet-4-20250514`): LOI + artist statement generation — quality matters

Both called through `utils/claude_client.py`. `_call()` retries up to 3 times with exponential backoff. Token usage accumulated per run via `threading.local()`, written to `run_logs` at run end.

## Flask Endpoints

| Method | Route | Auth | Description |
|--------|-------|------|-------------|
| GET | `/` | — | Health check |
| POST | `/run-agent` | ✓ | Trigger pipeline (background thread, returns 202) |
| GET | `/config` | ✓ | Load user config — 404 if not onboarded (dashboard gate) |
| POST | `/parse-resume` | ✓ | Parse artist CV / statement / past grant app (PDF) with Claude |
| GET | `/runs` | ✓ | Run history with grants (last 30 runs) |
| POST | `/onboard` | ✓ | Save user + full artist profile |
| POST | `/draft-document` | ✓ | Generate LOI or artist statement on demand |
| GET | `/drafts` | ✓ | List all saved drafts for user |

## CLI Flags (agent only)

```bash
python -m app.main [--mock] [--dry-run]
```

| Flag | Data source | DB writes | Claude | Email |
|------|------------|-----------|--------|-------|
| *(none)* | All grant sources | yes | full | sends |
| `--mock` | mock_grants.py | yes | full | prints |
| `--dry-run` | All grant sources | no | full | prints |
| `--mock --dry-run` | mock_grants.py | no | skipped | prints |

`--mock --dry-run` is fully offline, zero API cost — use for local testing without `DATABASE_URL`.

## Running Locally

```bash
cd agent
python3 -m venv .venv --copies && source .venv/bin/activate
pip install -r requirements.txt

# Fully offline test (verified working)
python -m app.main --mock --dry-run

# Flask server (requires .env with Firebase + DB)
python app/server.py
```

```bash
cd web
npm install
npm run dev   # http://localhost:3000
```

## Architectural Principles

- All eligibility and location logic lives in `scoring/filters.py` — never add geo or eligibility checks elsewhere
- All DB logic lives in `storage/grant_store.py` — never query Postgres directly from other modules
- All Claude calls go through `utils/claude_client.py` — never call the Anthropic SDK directly elsewhere
- LOI and artist statements are NEVER auto-generated by the pipeline — only via `POST /draft-document` triggered by the user
- Keep the pipeline decoupled from any single user's config — `get_user_config(user_id)` is the only entry point for user data
- Scoring is purely Claude-driven based on the user's profile and scoring weights — no hardcoded discipline boosts

## Infrastructure Reference

- **GCP project**: `stalwart-edge-453119-m6`
- **Cloud SQL instance**: `readymadehire-db`, region `us-central1`, IP `136.113.28.247`
- **Database**: `infinitemoneyglitch` (on the same instance as `readymadehire`)
- **Cloud Run service**: `infinitemoneyglitch-agent` (to be created — not deployed yet)
- **Firebase project**: to be created (separate from `readymade-hire-4276a`)
- **Resend sender domain**: `gugul.xyz` (already verified, shared with readymadehire)
- **⚠️ Local dev DB access**: IP allowlist needed for direct Postgres. Each session: `curl -s -4 ifconfig.me` → add `/32` to Cloud SQL → Connections → Networking → Authorized networks.

## Security Notes

- Never commit `.env`, `firebase-service-account.json`, or `web/.env.local`
- Firebase token verification is live on all endpoints — safe for real users after deploy
- Cloud SQL password must be confirmed before going public (check with Ibrahim)
- Firebase Google sign-in must be explicitly enabled in the new Firebase project before web auth works
