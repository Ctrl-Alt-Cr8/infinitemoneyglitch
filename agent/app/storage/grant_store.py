"""Postgres-backed grant memory and user config — all DB access lives here."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import date

import psycopg2
import psycopg2.extras
from psycopg2.pool import ThreadedConnectionPool


@dataclass
class UserConfig:
    user_id: str
    name: str
    disciplines: list
    org_type: str
    location_pref: str
    geographic_focus: list
    keywords: list
    summary: str
    constraints: str
    recipient_email: str
    project_description: str = ""
    past_grants: str = ""
    budget_min: int = 0
    deadline_window_days: int = 90
    scoring_weights: dict = field(default_factory=lambda: {"mission": "high", "award": "medium", "deadline": "medium"})
    interview_answers: str = ""

    def as_profile(self) -> dict:
        """Return profile dict shape expected by Claude prompts."""
        profile: dict = {
            "name": self.name,
            "disciplines": self.disciplines,
            "org_type": self.org_type,
            "location": self.location_pref,
            "geographic_focus": self.geographic_focus,
            "summary": self.summary,
            "constraints": self.constraints,
            "project_description": self.project_description,
            "scoring_weights": self.scoring_weights,
        }
        if self.past_grants:
            profile["past_grants"] = self.past_grants
        if self.budget_min:
            profile["budget_min"] = self.budget_min
            profile["budget_note"] = f"Minimum award size: ${self.budget_min:,} — score down grants below this"
        return profile


_pool: ThreadedConnectionPool | None = None


def _get_pool() -> ThreadedConnectionPool:
    global _pool
    if _pool is None:
        import urllib.parse
        dsn = os.environ["DATABASE_URL"]
        parsed = urllib.parse.urlparse(dsn)
        host = parsed.hostname or ""
        # Cloud Run passes the socket path as a query param: ?host=/cloudsql/...
        query = urllib.parse.parse_qs(parsed.query)
        socket_host = (query.get("host") or [""])[0]
        unix_socket = host.startswith("/") or socket_host.startswith("/")
        # For TCP, force IPv4 — macOS DNS64 translates IPv4 to IPv6 which Cloud SQL rejects.
        extra = {} if unix_socket else {"hostaddr": host}
        _pool = ThreadedConnectionPool(
            minconn=1,
            maxconn=10,
            dsn=dsn,
            **extra,
        )
    return _pool


def _connect():
    return _get_pool().getconn()


def _release(conn) -> None:
    _get_pool().putconn(conn)


def init_db() -> None:
    conn = _connect()
    try:
        with conn.cursor() as cur:
            # Advisory lock prevents concurrent gunicorn workers from deadlocking
            # on schema creation during simultaneous startup
            cur.execute("SELECT pg_advisory_lock(123456789)")
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id         TEXT PRIMARY KEY,
                    email      TEXT NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS user_configs (
                    user_id             TEXT PRIMARY KEY REFERENCES users(id),
                    name                TEXT NOT NULL,
                    disciplines         TEXT[],
                    org_type            TEXT,
                    location_pref       TEXT,
                    geographic_focus    TEXT[],
                    keywords            TEXT[],
                    summary             TEXT,
                    constraints         TEXT,
                    recipient_email     TEXT,
                    project_description TEXT,
                    past_grants         TEXT,
                    budget_min          INTEGER DEFAULT 0,
                    deadline_window_days INTEGER DEFAULT 90,
                    scoring_weights     JSONB,
                    interview_answers   TEXT,
                    updated_at          TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS grants (
                    id           SERIAL PRIMARY KEY,
                    user_id      TEXT NOT NULL,
                    title        TEXT NOT NULL,
                    funder       TEXT NOT NULL,
                    url          TEXT,
                    award_amount TEXT,
                    deadline     TEXT,
                    eligibility  TEXT,
                    disciplines  TEXT[],
                    org_types    TEXT[],
                    location     TEXT,
                    description  TEXT,
                    source       TEXT,
                    first_seen   DATE NOT NULL,
                    last_seen    DATE NOT NULL,
                    decision     TEXT,
                    email_sent   BOOLEAN DEFAULT FALSE,
                    score        INTEGER DEFAULT 0
                )
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_grants_user_title_funder
                ON grants (user_id, lower(title), lower(funder))
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS run_logs (
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
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS drafts (
                    id         SERIAL PRIMARY KEY,
                    user_id    TEXT NOT NULL REFERENCES users(id),
                    grant_id   INTEGER REFERENCES grants(id),
                    doc_type   TEXT NOT NULL,
                    content    TEXT NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            cur.execute("SELECT pg_advisory_unlock(123456789)")
        conn.commit()
    finally:
        _release(conn)


def _local_fallback_config(user_id: str) -> UserConfig:
    """Fallback when DATABASE_URL is not set (local CLI testing without DB)."""
    from app.config import PROFILE, KEYWORDS  # noqa: PLC0415
    return UserConfig(
        user_id=user_id,
        name=PROFILE["name"],
        disciplines=PROFILE["disciplines"],
        org_type=PROFILE["org_type"],
        location_pref=PROFILE["location"],
        geographic_focus=PROFILE["geographic_focus"],
        keywords=KEYWORDS,
        summary=PROFILE["summary"],
        constraints=PROFILE["constraints"],
        recipient_email=os.getenv("RECIPIENT_EMAIL", ""),
        project_description=PROFILE.get("project_description", ""),
        past_grants=PROFILE.get("past_grants", ""),
        budget_min=PROFILE.get("budget_min", 0),
        deadline_window_days=PROFILE.get("deadline_window_days", 90),
        scoring_weights=PROFILE.get("scoring_weights", {"mission": "high", "award": "medium", "deadline": "medium"}),
    )


def get_user_config(user_id: str) -> UserConfig:
    """Load per-user pipeline config. Falls back to local config.py if no DATABASE_URL."""
    if not os.getenv("DATABASE_URL"):
        return _local_fallback_config(user_id)

    conn = _connect()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM user_configs WHERE user_id = %s",
                (user_id,),
            )
            row = cur.fetchone()
    finally:
        _release(conn)

    if row is None:
        raise ValueError(f"No config found for user {user_id!r} — complete onboarding first.")

    weights = row.get("scoring_weights")
    if isinstance(weights, str):
        weights = json.loads(weights)
    if not weights:
        weights = {"mission": "high", "award": "medium", "deadline": "medium"}

    return UserConfig(
        user_id=user_id,
        name=row["name"],
        disciplines=list(row["disciplines"] or []),
        org_type=row.get("org_type") or "individual",
        location_pref=row.get("location_pref") or "",
        geographic_focus=list(row.get("geographic_focus") or []),
        keywords=list(row["keywords"] or []),
        summary=row.get("summary") or "",
        constraints=row.get("constraints") or "",
        recipient_email=row.get("recipient_email") or "",
        project_description=row.get("project_description") or "",
        past_grants=row.get("past_grants") or "",
        budget_min=int(row.get("budget_min") or 0),
        deadline_window_days=int(row.get("deadline_window_days") or 90),
        scoring_weights=weights,
        interview_answers=row.get("interview_answers") or "",
    )


def get_runs_with_grants(user_id: str) -> list:
    conn = _connect()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, run_at, grants_fetched, grants_priority, grants_review, grants_skip, estimated_cost
                FROM run_logs
                WHERE user_id = %s
                ORDER BY run_at DESC
                LIMIT 30
                """,
                (user_id,),
            )
            runs = [dict(r) for r in cur.fetchall()]

            for run in runs:
                run_date = run["run_at"].date()
                cur.execute(
                    """
                    SELECT id, title, funder, award_amount, deadline, decision, score, url, disciplines, eligibility
                    FROM grants
                    WHERE user_id = %s AND first_seen = %s
                    ORDER BY
                        CASE decision WHEN 'PRIORITY' THEN 1 WHEN 'REVIEW' THEN 2 ELSE 3 END,
                        score DESC
                    """,
                    (user_id, run_date),
                )
                run["grants"] = [dict(g) for g in cur.fetchall()]
                run["run_at"] = run["run_at"].isoformat()
                run["estimated_cost"] = float(run["estimated_cost"] or 0)
    finally:
        _release(conn)
    return runs


def save_user(user_id: str, email: str) -> None:
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO users (id, email)
                VALUES (%s, %s)
                ON CONFLICT (id) DO UPDATE SET email = EXCLUDED.email
                """,
                (user_id, email),
            )
        conn.commit()
    finally:
        _release(conn)


def save_user_config(
    user_id: str,
    name: str,
    disciplines: list,
    org_type: str,
    location_pref: str,
    geographic_focus: list,
    keywords: list,
    summary: str,
    constraints: str,
    recipient_email: str,
    project_description: str = "",
    past_grants: str = "",
    budget_min: int = 0,
    deadline_window_days: int = 90,
    scoring_weights: dict | None = None,
    interview_answers: str = "",
) -> None:
    if scoring_weights is None:
        scoring_weights = {"mission": "high", "award": "medium", "deadline": "medium"}
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO user_configs
                    (user_id, name, disciplines, org_type, location_pref, geographic_focus, keywords,
                     summary, constraints, recipient_email, project_description, past_grants,
                     budget_min, deadline_window_days, scoring_weights, interview_answers)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (user_id) DO UPDATE SET
                    name                 = EXCLUDED.name,
                    disciplines          = EXCLUDED.disciplines,
                    org_type             = EXCLUDED.org_type,
                    location_pref        = EXCLUDED.location_pref,
                    geographic_focus     = EXCLUDED.geographic_focus,
                    keywords             = EXCLUDED.keywords,
                    summary              = EXCLUDED.summary,
                    constraints          = EXCLUDED.constraints,
                    recipient_email      = EXCLUDED.recipient_email,
                    project_description  = EXCLUDED.project_description,
                    past_grants          = EXCLUDED.past_grants,
                    budget_min           = EXCLUDED.budget_min,
                    deadline_window_days = EXCLUDED.deadline_window_days,
                    scoring_weights      = EXCLUDED.scoring_weights,
                    interview_answers    = EXCLUDED.interview_answers,
                    updated_at           = NOW()
                """,
                (user_id, name, disciplines, org_type, location_pref, geographic_focus, keywords,
                 summary, constraints, recipient_email, project_description, past_grants,
                 budget_min, deadline_window_days, json.dumps(scoring_weights), interview_answers),
            )
        conn.commit()
    finally:
        _release(conn)


def is_known_grant(title: str, funder: str, user_id: str) -> bool:
    t = (title or "").strip()
    f = (funder or "").strip()
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM grants WHERE user_id = %s AND lower(title) = lower(%s) AND lower(funder) = lower(%s)",
                (user_id, t, f),
            )
            return cur.fetchone() is not None
    finally:
        _release(conn)


def update_last_seen(title: str, funder: str, user_id: str) -> None:
    today = date.today()
    t = (title or "").strip()
    f = (funder or "").strip()
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE grants SET last_seen = %s WHERE user_id = %s AND lower(title) = lower(%s) AND lower(funder) = lower(%s)",
                (today, user_id, t, f),
            )
        conn.commit()
    finally:
        _release(conn)


def record_grant(grant: dict, decision: str, score: int, email_sent: bool, user_id: str) -> None:
    today = date.today()
    title = (grant.get("title") or "").strip()
    funder = (grant.get("funder") or "").strip()
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO grants
                    (user_id, title, funder, url, award_amount, deadline, eligibility,
                     disciplines, org_types, location, description, source,
                     first_seen, last_seen, decision, email_sent, score)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (user_id, title, funder,
                 grant.get("url") or "",
                 grant.get("award_amount") or "",
                 grant.get("deadline") or "",
                 grant.get("eligibility") or "",
                 grant.get("disciplines") or [],
                 grant.get("org_types") or [],
                 grant.get("location") or "",
                 grant.get("description") or "",
                 grant.get("source") or "",
                 today, today, decision, email_sent, score),
            )
        conn.commit()
    finally:
        _release(conn)


def get_grant(grant_id: int) -> dict | None:
    conn = _connect()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM grants WHERE id = %s", (grant_id,))
            row = cur.fetchone()
            return dict(row) if row else None
    finally:
        _release(conn)


def save_draft(user_id: str, grant_id: int | None, doc_type: str, content: str) -> int:
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO drafts (user_id, grant_id, doc_type, content)
                VALUES (%s, %s, %s, %s)
                RETURNING id
                """,
                (user_id, grant_id, doc_type, content),
            )
            draft_id = cur.fetchone()[0]
        conn.commit()
        return draft_id
    finally:
        _release(conn)


def get_drafts(user_id: str) -> list:
    conn = _connect()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT d.id, d.grant_id, d.doc_type, d.content, d.created_at,
                       g.title AS grant_title, g.funder
                FROM drafts d
                LEFT JOIN grants g ON g.id = d.grant_id
                WHERE d.user_id = %s
                ORDER BY d.created_at DESC
                """,
                (user_id,),
            )
            drafts = [dict(r) for r in cur.fetchall()]
            for d in drafts:
                d["created_at"] = d["created_at"].isoformat()
        return drafts
    finally:
        _release(conn)


def record_run_log(
    user_id: str,
    grants_fetched: int,
    grants_priority: int,
    grants_review: int,
    grants_skip: int,
    haiku_tokens: int,
    sonnet_tokens: int,
    estimated_cost: float,
) -> None:
    if not os.getenv("DATABASE_URL"):
        return
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO run_logs
                    (user_id, grants_fetched, grants_priority, grants_review, grants_skip,
                     haiku_tokens, sonnet_tokens, estimated_cost)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (user_id, grants_fetched, grants_priority, grants_review, grants_skip,
                 haiku_tokens, sonnet_tokens, estimated_cost),
            )
        conn.commit()
    finally:
        _release(conn)
