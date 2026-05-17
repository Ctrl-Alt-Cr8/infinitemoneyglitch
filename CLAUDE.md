# CLAUDE.md

This file provides guidance to Claude Code when working in this repository.

## What This Project Is

Readymade.hire SaaS is a multi-user platform built on top of the Readymade.hire job agent engine. The engine fetches job listings, scores them for fit using Claude, generates tailored cover letters, and sends a daily report email. The SaaS layer adds user accounts, per-user config, a web UI, and cost tracking so multiple users can run their own job search agents.

The engine code (in `agent/`) is carried over from the original solo agent repo and is production-tested. Changes to the engine should be surgical — don't restructure it, just extend it.

## Repo Structure

```
agent/    # Python pipeline — Flask server, Claude API, job scoring, cover letters
web/      # Next.js frontend — Firebase Auth, onboarding, dashboard
```

## Stack

- **Agent**: Python, Flask, Cloud Run (GCP)
- **AI**: Claude Haiku (scoring) + Claude Sonnet (cover letters) via Anthropic API
- **DB**: Cloud SQL (Postgres) — connection via `DATABASE_URL` env var
- **Auth**: Firebase Auth (ID token verified on agent, Firebase SDK on web)
- **Web**: Next.js 16, TypeScript, Tailwind CSS
- **CI/CD**: Cloud Build → Cloud Run (agent), Vercel (web)
- **Job sources**: SerpAPI (primary) → Serper.dev (per-keyword fallback)

## Build Plan & Current Status

### Done
- [x] Engine copied from solo agent repo into `agent/` — pipeline is production-tested
- [x] SQLite swapped for Postgres (`psycopg2` + connection pool via `DATABASE_URL`)
- [x] `user_id` threaded through entire pipeline — all DB records are user-scoped from day one
- [x] `run_pipeline(user_id)` and `run()` accept user_id; server.py passes it to background thread
- [x] **Task 2** — Per-user config: `users` + `user_configs` tables live in Postgres. `UserConfig` dataclass + `get_user_config(user_id)` in `job_store.py`. Config (profile + keywords) loaded at pipeline start and threaded through scorer, cover letter, and fetcher. Falls back to `config.py` for local CLI testing when no `DATABASE_URL`. Ibrahim's config seeded as the `default` user.
- [x] **Task 3** — Firebase Auth on `/run-agent`: `firebase-admin` installed, `_verify_token()` verifies Bearer token, real Firebase UID used as `user_id`. Returns 401 on missing/invalid/expired token.
- [x] **Task 4** — Per-run cost logging: thread-local token accumulator in `claude_client.py` tracks Haiku + Sonnet input/output tokens per run. `run_logs` table live in Postgres. `record_run_log()` writes cost after every non-dry-run. Pricing: Haiku $0.80/$4.00 per MTok in/out, Sonnet $3.00/$15.00.
- [x] **Task 5** — Next.js scaffold in `web/`: TypeScript + Tailwind, Firebase Auth wired up with `AuthProvider` context, Google sign-in only, login page (`/`) redirects to dashboard if signed in, dashboard stub (`/dashboard`) redirects to login if signed out. Build passes clean.

### Done (continued)
- [x] **Task 6** — Onboarding flow: `GET /config` gate on dashboard, `POST /parse-resume` (pypdf + Claude Haiku extracts profile), `POST /onboard` (upserts users + user_configs). Web: `/onboarding` page with resume-upload path (pre-fills editable form) and manual path. Tested end-to-end — resume upload, form edit, submit, redirect to dashboard all working.
- [x] **Task 7** — Dashboard UI tested and working: run history cards, APPLY/REVIEW/SKIP badges, Run Agent button. Shows real runs (zeros expected — no job source API keys set yet).
- [x] **Task 8** — Agent live on Cloud Run: `https://readymadehire-agent-347263305441.us-central1.run.app`. Cloud SQL via Unix socket (Auth Proxy — no IP allowlisting). Firebase SA in Secret Manager. `web/.env.local` points at Cloud Run.
- [x] **Task 9** — Pipeline working end-to-end: SerpAPI primary (20 results/keyword, location-aware), Serper fallback. Email via Resend from `noreply@gugul.xyz`. APPLY threshold lowered to 85.
- [x] **Task 10 (partial)** — Enhanced onboarding: interview step (roles wanted, industries, work env, job type, min salary, years experience, open field). Keyword tag editor (add/remove/reorder). Claude uses resume + interview answers together for better keyword/profile generation. All new fields stored in `user_configs`. Deployed to Cloud Run.

### To Do (in order)

**Task 13 — Invite first demo users** ← IN PROGRESS
First batch: product management + construction users already invited. Instagram story sent — expecting 5-7 total demo users. Each user completes onboarding + runs agent. Review cost logs per user before scaling.

**Task 14 — Run scheduling**
Add ability for users to schedule automatic daily runs instead of manually hitting Run Agent. Agent-side cron or Cloud Scheduler trigger per user.

**Task 15 — Voice-matched cover letters**
Upload writing samples or existing cover letters so Claude can match the user's tone and style.

### Future Projects (Next Session Priority)

**Grant & Funding Finder (spin-off)**
Clone this repo and adapt the pipeline for artists and community organizers searching for grants/funding instead of jobs. ~70% of the codebase carries over unchanged.

What maps directly: all infrastructure (Postgres, Firebase, Cloud Run, Vercel), pipeline architecture (fetch → score → filter → email digest), per-user config, cost logging, onboarding flow, web frontend structure.

What needs building:
- **Fetchers** — Grants.gov free REST API (federal), SerpAPI grant-specific queries, state/local arts council scraping
- **Scoring prompt** — rewrite for grant fit: mission alignment, eligibility, award size, deadline proximity
- **User profile** — discipline, org type (individual/nonprofit/collective), past grants, project descriptions, budget range
- **Cover letter → LOI generator** — same two-pass Claude pattern, different prompt
- **DB schema** — `grants` table with `deadline`, `award_amount`, `eligibility`, `funder` fields
- **Filters** — eligibility-based (501c3 required? individual artists only? geographic restrictions?)

Estimated effort: 2–3 weeks. Hardest part is grant data sourcing — federal well-covered, local/private foundations are fragmented.

### Done (Tasks 11–12)
- [x] **Task 12** — Web deployed to Vercel. Repo made public, all env vars set, Firebase authorized domain added. Google sign-in working end-to-end.
- [x] **Task 11** — Job sources wired: JSearch (RapidAPI `/search` endpoint), Adzuna, The Muse all live in `fetcher_router.py`. Keys in Cloud Run env vars. SerpAPI + Serper still primary per-keyword; new sources run as supplementary.
- [x] **SaaS audit + universalization** — Removed all Ibrahim-specific hardcoding: filters now driven by user's `target_roles`, location filter uses user's `location_pref`, `config.py` fallback is anonymous, mock jobs are profession-neutral, email sender uses `SENDER_EMAIL` env var (gugul.xyz).
- [x] **Bug fixes** — JSearch switched to `/search` (free tier), `init_db()` advisory lock prevents gunicorn startup deadlock, None-safe filename sanitizer, type guards on all new fetcher response shapes.
- [x] **Pipeline verified end-to-end** — Full run completes: fetch → score → email → dashboard. Tested with education-profession user.

## Infrastructure (Live)

- **Cloud SQL instance**: `readymadehire-db`, project `stalwart-edge-453119-m6`, region `us-central1`
- **DB**: `readymadehire` (Postgres), IP `136.113.28.247`, user `postgres`
- **DB tables**: `users`, `user_configs`, `jobs`, `run_logs` — all live
- **Seeded**: `default` user in `users` + `user_configs` (Ibrahim's config, for CLI runs)
- **Firebase project**: `readymade-hire-4276a`
- **Firebase service account key**: `agent/firebase-service-account.json` (gitignored); stored in Secret Manager as `firebase-service-account` for Cloud Run
- **Cloud Run service**: `readymadehire-agent`, `https://readymadehire-agent-347263305441.us-central1.run.app`
- **Cloud Run DB**: connects via Unix socket (Cloud SQL Auth Proxy) — no IP allowlisting needed in production
- **⚠️ Local dev only**: IP allowlist still needed for direct Postgres access from your machine. Each session: `curl -s -4 ifconfig.me` → add `/32` to Cloud SQL → Connections → Networking → Authorized networks. (Not needed if you only test against Cloud Run URL.)

## Onboarding Design Decisions

- **Sign-in**: Google only (no email/password)
- **Profile entry**: resume upload (Claude extracts profile + suggests keywords) OR manual form — user's choice
- **Report delivery**: user enters a recipient email address during onboarding (stored in `user_configs.recipient_email`). Does not have to match their Google account email.
- **Demo group**: diverse professions (construction, product management, teaching, AI, etc.) — pipeline is NOT AI-specific. Scorer is fully Claude-driven based on each user's profile.

## Agent Architecture & Data Flow

The pipeline in `agent/app/main.py` runs in order:

1. **Load config** (`storage/job_store.py → get_user_config(user_id)`): Loads `UserConfig` from Postgres (or falls back to `config.py` if no `DATABASE_URL`).
2. **Fetch** (`sources/fetcher_router.py → fetch_all_jobs(keywords)`): Tries SerpAPI per keyword first; falls back to Serper.dev if SerpAPI returns empty. Keywords come from `user_configs`.
3. **Disqualify** (`scoring/filters.py → disqualify_jobs()`): Hard-blocks non-AI, research, and fellowship roles.
4. **Filter** (`scoring/filters.py → passes_filters()`): Soft filters for role type and location. All location logic lives here — never add location filtering elsewhere.
5. **Memory filter** (`storage/job_store.py → is_known_job()`): Skips jobs already seen by this user. Checks by `user_id + title + company`.
6. **Score** (`scoring/scorer.py → score_jobs_batch(jobs, profile)`): Batches 8 jobs at a time to Claude Haiku. Scoring is purely Claude-driven based on the user's profile — no hardcoded keyword boosts.
7. **Decide**: Top 20 scored jobs. Score ≥ 88 AND passes `qualifies_for_apply()` → APPLY; 70–87 OR fails qualify → REVIEW; < 70 → SKIP.
8. **Cover letters** (`composer/cover_letter.py → generate_cover_letter(job, profile)`): Claude Sonnet generates letters for APPLY jobs. Two-pass: generate → validate → retry once if needed. Prompt is generalized for any profession.
9. **Daily report** (`utils/send_email.py`): One email per run to `user_configs.recipient_email`. APPLY section (with cover letter) then REVIEW section.
10. **Record** (`storage/job_store.py → record_job()`): All processed jobs written to Postgres with `user_id`, decision, score, and `email_sent`.
11. **Cost log** (`storage/job_store.py → record_run_log()`): Token counts + estimated cost written to `run_logs`.

## Database Schema

All tables are live in Cloud SQL (`readymadehire` database).

```sql
-- One row per registered user (Firebase UID as primary key)
CREATE TABLE users (
    id         TEXT PRIMARY KEY,
    email      TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Per-user pipeline config
CREATE TABLE user_configs (
    user_id         TEXT PRIMARY KEY REFERENCES users(id),
    name            TEXT NOT NULL,
    target_roles    TEXT[],
    location_pref   TEXT,
    keywords        TEXT[],
    summary         TEXT,
    constraints     TEXT,
    recipient_email TEXT,
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Tracks all jobs seen and processed per user
CREATE TABLE jobs (
    id         SERIAL PRIMARY KEY,
    user_id    TEXT NOT NULL,
    title      TEXT NOT NULL,
    company    TEXT NOT NULL,
    first_seen DATE NOT NULL,
    last_seen  DATE NOT NULL,
    decision   TEXT,
    email_sent BOOLEAN DEFAULT FALSE,
    score      INTEGER DEFAULT 0
);

-- Per-run cost and summary log
CREATE TABLE run_logs (
    id             SERIAL PRIMARY KEY,
    user_id        TEXT NOT NULL REFERENCES users(id),
    run_at         TIMESTAMPTZ DEFAULT NOW(),
    jobs_fetched   INTEGER,
    jobs_apply     INTEGER,
    jobs_review    INTEGER,
    jobs_skip      INTEGER,
    haiku_tokens   INTEGER,
    sonnet_tokens  INTEGER,
    estimated_cost NUMERIC(8, 4)
);
```

## Environment Variables

### `agent/.env` (local) / Cloud Run env vars (production)

```
# Anthropic
ANTHROPIC_API_KEY=

# Job sources
SERPAPI_API_KEY=
SERPER_API_KEY=

# Email
GMAIL_USER=
GMAIL_APP_PASSWORD=

# Database
DATABASE_URL=postgresql://postgres:<password>@136.113.28.247:5432/readymadehire

# Firebase Admin SDK
FIREBASE_SERVICE_ACCOUNT=firebase-service-account.json  # path locally; JSON string on Cloud Run

# CLI-only (used for --mock / --dry-run; server uses real Firebase UID)
USER_ID=default
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
NEXT_PUBLIC_AGENT_URL=http://localhost:8080  # update to Cloud Run URL after Task 8
```

## Claude Model Usage

- **Claude Haiku** (`claude-haiku-4-5-20251001`): Job scoring — cheap, batch-optimized
- **Claude Sonnet** (`claude-sonnet-4-20250514`): Cover letter generation — higher quality

Both called through `utils/claude_client.py`. `_call()` retries up to 3 times with exponential backoff. Token usage is accumulated per run using a `threading.local()` store and written to `run_logs` at the end of each run.

## CLI Flags (agent only)

```bash
python -m app.main [--mock] [--dry-run]
```

| Flag | Data source | DB writes | Claude | Email |
|------|------------|-----------|--------|-------|
| *(none)* | SerpAPI → Serper | yes | full | sends |
| `--mock` | mock_jobs.py | yes | full | prints |
| `--dry-run` | SerpAPI → Serper | no | full | prints |
| `--mock --dry-run` | mock_jobs.py | no | skipped | prints |

`--mock --dry-run` combined is fully offline, zero API cost — use for local testing without `DATABASE_URL`.

## Architectural Principles (Do Not Violate)

- All location logic lives in `scoring/filters.py` — never add location checks elsewhere
- All DB logic lives in `storage/job_store.py` — never query Postgres directly from other modules
- All Claude calls go through `utils/claude_client.py` — never call the Anthropic SDK directly elsewhere
- Keep the pipeline engine decoupled from any single user's config — `get_user_config(user_id)` is the only entry point for user data in the pipeline
- Greenhouse and Lever sources are commented out in `fetcher_router.py` — do not re-enable without investigating the hang issue
- The cover letter prompt in `_build_cover_letter_prompt()` is generalized for any profession — do not re-introduce Ibrahim-specific framing or Readymade.AI references

## Running Locally

```bash
cd agent
python3 -m venv .venv --copies && source .venv/bin/activate
pip install -r requirements.txt

# Fully offline test (no API costs, no DB needed — uses config.py fallback)
python -m app.main --mock --dry-run

# Full pipeline (requires .env with all keys + DATABASE_URL)
python -m app.main

# Flask server
python app/server.py
```

```bash
cd web
npm install
npm run dev   # runs at localhost:3000
```

## Security Notes

- Firebase token verification is live on `/run-agent` — real users are safe to onboard after Task 6
- Never commit `.env`, `firebase-service-account.json`, or `web/.env.local`
- Before any public-facing deploy: rotate all API keys, move secrets to GCP Secret Manager
- Cloud SQL password (`r00tacc3ss`) must be rotated before going public
- Firebase Google sign-in must be enabled in Firebase Console → Authentication → Sign-in method → Google → Enable (required before web auth works)
