# job-agent

A modular Python CLI application that fetches job listings, scores role relevance with Claude, and generates tailored cover letters.

## What this project does

- Pulls job listings from a mock source (`app/sources/mock_jobs.py`)
- Scores each role against your profile using Claude (`app/scoring/scorer.py`)
- Generates a targeted cover letter for each role (`app/composer/cover_letter.py`)
- Prints a clean terminal workflow with `rich` (`app/main.py`)

## Tech stack

- Python 3.11+
- anthropic (Claude API)
- python-dotenv
- requests
- rich
- SQLite scaffold placeholder (`app/storage/`)

## Setup

1. Create and activate a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Configure environment variables:

```bash
cp .env.example .env
```

Then set `ANTHROPIC_API_KEY` in `.env`.

## Run the CLI

From the `job-agent` directory:

```bash
python -m app.main
```

## Future roadmap

- Integrate real job APIs (LinkedIn, Greenhouse, Lever, etc.)
- Add SQLite-backed persistence and scoring history
- Automate apply pipelines and response tracking
- Add Notion integration for job queue + generated documents
- Evolve into multi-tenant SaaS architecture
