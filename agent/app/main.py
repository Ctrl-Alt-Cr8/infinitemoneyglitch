"""CLI entrypoint for the grant-finder pipeline."""

from __future__ import annotations

import argparse
from datetime import date
import json
import os

from rich.console import Console
from rich.table import Table

from app.scoring.filters import disqualify_grants, passes_filters, get_eligibility_status
from app.scoring.scorer import score_grant, score_grants_batch
from app.sources.fetcher_router import fetch_all_grants
from app.sources.mock_grants import get_grants as get_mock_grants
from app.storage.grant_store import (
    init_db, is_known_grant, record_grant, update_last_seen,
    get_user_config, record_run_log,
)
from app.utils.claude_client import reset_token_counts, get_token_counts
from app.utils.send_email import send_email


console = Console()

PRIORITY_THRESHOLD = 85
REVIEW_THRESHOLD = 70
MAX_GRANTS_TO_SCORE = 50


def safe_ascii(text: str) -> str:
    return (
        str(text)
        .replace("\xa0", " ")
        .replace("—", "-")
        .encode("ascii", "ignore")
        .decode()
    )


def _deadline_display(deadline: str | None) -> str:
    """Format deadline with urgency indicator if within 30 days."""
    if not deadline:
        return "Unknown"
    dl = deadline.strip().lower()
    if dl in ("rolling", "ongoing", "open"):
        return "Rolling"
    try:
        parts = deadline.strip().split("-")
        if len(parts) == 3:
            dl_date = date(int(parts[0]), int(parts[1]), int(parts[2]))
            days_left = (dl_date - date.today()).days
            if days_left <= 0:
                return f"{deadline} (CLOSED)"
            if days_left <= 30:
                return f"{deadline} ({days_left} days left - URGENT)"
            return deadline
    except Exception:
        pass
    return deadline


def run(mock: bool = False, dry_run: bool = False, user_id: str = "") -> None:
    """Fetch grants, score relevance and eligibility, send digest email."""
    if not user_id:
        user_id = os.getenv("USER_ID", "default")

    config = get_user_config(user_id)
    profile = config.as_profile()
    recipient_email = config.recipient_email or os.getenv("RECIPIENT_EMAIL", "")

    reset_token_counts()

    os.makedirs("outputs", exist_ok=True)
    if os.getenv("DATABASE_URL"):
        init_db()

    if mock:
        grants = get_mock_grants()
        print(f"[MOCK] Loaded {len(grants)} mock grants")
    else:
        grants = fetch_all_grants(config)
        print(f"Fetched {len(grants)} grants")

    grants_fetched = len(grants)

    grants = disqualify_grants(grants, config)
    print(f"After disqualification: {len(grants)} grants")

    grants = [g for g in grants if passes_filters(g, config)]
    print(f"After filtering: {len(grants)} grants")

    new_grants = []
    skipped_known = 0
    if os.getenv("DATABASE_URL"):
        for grant in grants:
            if is_known_grant(grant.get("title", ""), grant.get("funder", ""), user_id=user_id):
                if not dry_run:
                    update_last_seen(grant.get("title", ""), grant.get("funder", ""), user_id=user_id)
                skipped_known += 1
            else:
                new_grants.append(grant)
        if skipped_known:
            print(f"Skipped {skipped_known} already-seen grant(s)")
        grants = new_grants
    else:
        new_grants = grants
    print(f"After memory filter: {len(grants)} new grant(s)")

    if len(grants) > MAX_GRANTS_TO_SCORE:
        grants = grants[:MAX_GRANTS_TO_SCORE]
        print(f"Capped to {MAX_GRANTS_TO_SCORE} grants for scoring")

    mode = ""
    if mock or dry_run:
        mode = "MOCK + DRY RUN" if (mock and dry_run) else "MOCK" if mock else "DRY RUN"
        print(f"Mode: {mode}")
    console.print("[bold cyan]grant-finder[/bold cyan] • Starting pipeline\n")

    # Build eligibility map for scorer
    eligibility_map: dict[int, str] = {}
    for i, grant in enumerate(grants):
        eligibility_map[i] = get_eligibility_status(grant, config)

    scored_grants: list[dict] = []
    if mock and dry_run:
        for grant in grants:
            scored_grants.append({
                "grant": grant,
                "score": {
                    "score": grant.get("mock_score", 75),
                    "eligibility_status": "unclear",
                    "why_fit": "[mock — no Claude call]",
                    "mission_alignment": "[mock — no Claude call]",
                    "gaps": "[mock — no Claude call]",
                },
            })
        print(f"[DRY RUN] Using mock scores for {len(grants)} grants (no Claude call)")
    else:
        try:
            scores = score_grants_batch(grants, profile, eligibility_map=eligibility_map)
            for grant, score in zip(grants, scores):
                scored_grants.append({"grant": grant, "score": score})
        except Exception as e:
            print(f"Batch scoring failed, falling back to individual: {e}")
            for i, grant in enumerate(grants):
                score = score_grant(grant, profile, eligibility_status=eligibility_map.get(i, "unclear"))
                scored_grants.append({"grant": grant, "score": score})

    scored_grants = sorted(scored_grants, key=lambda x: x["score"]["score"], reverse=True)
    top_grants = scored_grants[:20]

    priority_count = 0
    review_count = 0
    skip_count = 0
    results: list[dict] = []
    priority_grants: list[dict] = []
    review_grants: list[dict] = []

    for index, item in enumerate(top_grants, start=1):
        grant = item["grant"]
        score = item["score"]
        console.rule(f"Grant {index}: {grant.get('title', '')} — {grant.get('funder', '')}")

        if score["score"] >= PRIORITY_THRESHOLD:
            decision = "PRIORITY"
            priority_count += 1
        elif score["score"] >= REVIEW_THRESHOLD:
            decision = "REVIEW"
            review_count += 1
        else:
            decision = "SKIP"
            skip_count += 1

        grant["decision"] = decision

        results.append({
            "funder": grant.get("funder", ""),
            "title": grant.get("title", ""),
            "award_amount": grant.get("award_amount", ""),
            "deadline": grant.get("deadline", ""),
            "score": score.get("score", 0),
            "decision": decision,
            "url": grant.get("url", ""),
            "eligibility_status": score.get("eligibility_status", "unclear"),
            "why_fit": score.get("why_fit", ""),
            "gaps": score.get("gaps", ""),
        })

        decision_styles = {
            "PRIORITY": "bold green",
            "REVIEW": "bold yellow",
            "SKIP": "bold red",
        }
        decision_display = f"[{decision_styles[decision]}]{decision}[/{decision_styles[decision]}]"

        table = Table(show_header=False, box=None)
        table.add_row("Funder", grant.get("funder", ""))
        table.add_row("Title", grant.get("title", ""))
        table.add_row("Award", grant.get("award_amount") or "Not specified")
        table.add_row("Deadline", _deadline_display(grant.get("deadline")))
        table.add_row("Location", grant.get("location") or "Not specified")
        table.add_row("Source", grant.get("source", "-"))
        table.add_row("URL", grant.get("url", "-"))
        table.add_row("Score", f"[bold green]{score['score']}[/bold green]/100")
        table.add_row("Eligibility", score.get("eligibility_status", "unclear"))
        table.add_row("Decision", decision_display)
        table.add_row("Why Fit", score.get("why_fit", ""))
        table.add_row("Mission Alignment", score.get("mission_alignment", ""))
        table.add_row("Gaps", score.get("gaps", ""))
        console.print(table)

        if decision not in ("PRIORITY", "REVIEW"):
            if not dry_run:
                record_grant(grant, decision, score.get("score", 0), email_sent=False, user_id=user_id)
            continue

        entry = {
            "funder": grant.get("funder", ""),
            "title": grant.get("title", ""),
            "award_amount": grant.get("award_amount") or "Not specified",
            "deadline": _deadline_display(grant.get("deadline")),
            "url": grant.get("url", ""),
            "score": score.get("score", 0),
            "eligibility_status": score.get("eligibility_status", "unclear"),
            "why_fit": score.get("why_fit", ""),
            "mission_alignment": score.get("mission_alignment", ""),
            "gaps": score.get("gaps", ""),
            "_grant": grant,
        }

        if decision == "PRIORITY":
            priority_grants.append(entry)
        else:
            review_grants.append(entry)

    # Email digest — no documents attached (drafting is on-demand from dashboard)
    today_str = date.today().isoformat()
    total_new = len(priority_grants) + len(review_grants)

    if total_new == 0:
        report_subject = safe_ascii(f"[Infinite Money Glitch] Grant Digest — {today_str} — No new grants")
        report_body = safe_ascii(f"No new grants found today ({today_str}).")
    else:
        report_subject = safe_ascii(
            f"[Infinite Money Glitch] Grant Digest — {today_str} — {total_new} new grant(s)"
        )
        lines: list[str] = [
            "GRANT DIGEST",
            f"Date: {today_str}",
            f"New grants: {total_new}",
            "",
            "Draft LOIs and artist statements for your top matches in the dashboard.",
            "",
        ]

        if priority_grants:
            pg_sorted = sorted(priority_grants, key=lambda x: x["score"], reverse=True)
            lines.append(f"--- PRIORITY ({len(pg_sorted)} grant(s)) ---")
            lines.append("")
            for i, pg in enumerate(pg_sorted, 1):
                lines.append(f"{i}. {pg['funder']} — {pg['title']}")
                lines.append(f"   Award    : {pg['award_amount']}")
                lines.append(f"   Deadline : {pg['deadline']}")
                lines.append(f"   Eligible : {pg['eligibility_status']}")
                lines.append(f"   Score    : {pg['score']}/100")
                lines.append(f"   Why Fit  : {pg['why_fit']}")
                lines.append(f"   Link     : {pg['url']}")
                lines.append("")

        if review_grants:
            rg_sorted = sorted(review_grants, key=lambda x: x["score"], reverse=True)
            lines.append(f"--- REVIEW ({len(rg_sorted)} grant(s)) ---")
            lines.append("")
            for i, rg in enumerate(rg_sorted, 1):
                lines.append(f"{i}. {rg['funder']} — {rg['title']}")
                lines.append(f"   Award    : {rg['award_amount']}")
                lines.append(f"   Deadline : {rg['deadline']}")
                lines.append(f"   Score    : {rg['score']}/100")
                lines.append(f"   Why Fit  : {rg['why_fit']}")
                lines.append(f"   Gaps     : {rg['gaps']}")
                lines.append(f"   Link     : {rg['url']}")
                lines.append("")

        report_body = safe_ascii("\n".join(lines))

    report_sent = False
    if dry_run or mock:
        prefix = "[DRY RUN]" if dry_run else "[MOCK]"
        print(f"\n{prefix} Would send to: {recipient_email}")
        print(f"{prefix} Subject: {report_subject}")
        print(f"{prefix} Body:\n{report_body}")
    else:
        try:
            print(f"Sending digest to: {recipient_email}")
            send_email(to_email=recipient_email, subject=report_subject, body=report_body)
            report_sent = True
            print("Digest sent.")
        except Exception as error:
            print(f"Email error: {error}")

    if not dry_run:
        for entry in priority_grants:
            record_grant(entry["_grant"], "PRIORITY", entry["score"], email_sent=report_sent, user_id=user_id)
        for entry in review_grants:
            record_grant(entry["_grant"], "REVIEW", entry["score"], email_sent=report_sent, user_id=user_id)

        tokens = get_token_counts()
        record_run_log(
            user_id=user_id,
            grants_fetched=grants_fetched,
            grants_priority=priority_count,
            grants_review=review_count,
            grants_skip=skip_count,
            haiku_tokens=tokens["haiku_tokens"],
            sonnet_tokens=tokens["sonnet_tokens"],
            estimated_cost=tokens["estimated_cost"],
        )
        print(f"Run cost: ${tokens['estimated_cost']:.4f} "
              f"(Haiku: {tokens['haiku_tokens']} tokens, Sonnet: {tokens['sonnet_tokens']} tokens)")

    results = sorted(results, key=lambda x: x["score"], reverse=True)
    with open(os.path.join("outputs", "grants.json"), "w", encoding="utf-8") as handle:
        json.dump(results[:20], handle, indent=2)

    console.print("\n[bold green]Done.[/bold green] Pipeline complete.")
    summary = Table(show_header=False, box=None)
    summary.add_row("Grants evaluated", str(len(scored_grants)))
    summary.add_row("PRIORITY", f"[bold green]{priority_count}[/bold green]")
    summary.add_row("REVIEW", f"[bold yellow]{review_count}[/bold yellow]")
    summary.add_row("SKIP", f"[bold red]{skip_count}[/bold red]")
    console.print("\n[bold]Summary:[/bold]")
    console.print(summary)


def run_pipeline(user_id: str = "default"):
    """Wrapper called by server.py background thread."""
    run(user_id=user_id)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Infinite Money Glitch grant-finder pipeline")
    parser.add_argument("--mock", action="store_true", help="Use mock grant data")
    parser.add_argument("--dry-run", action="store_true", dest="dry_run",
                        help="Skip email and DB writes; combine with --mock to skip Claude calls")
    args = parser.parse_args()
    run(mock=args.mock, dry_run=args.dry_run)
