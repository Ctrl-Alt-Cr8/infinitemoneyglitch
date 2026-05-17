"""Grant fetcher orchestrator — all grant sources funnel through here."""

import os
import re
import requests
from serpapi import GoogleSearch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clean_html(text: str) -> str:
    return re.sub(r"<[^>]+>", " ", text or "").strip()


def _truncate(text: str, max_chars: int = 3000) -> str:
    return (text or "")[:max_chars]


def _grant_shape(
    funder: str,
    title: str,
    description: str,
    url: str,
    award_amount: str | None = None,
    deadline: str | None = None,
    eligibility: str | None = None,
    disciplines: list | None = None,
    org_types: list | None = None,
    location: str | None = None,
    source: str = "",
) -> dict:
    return {
        "funder": (funder or "").strip(),
        "title": (title or "").strip(),
        "description": _truncate(_clean_html(description)),
        "url": (url or "").strip(),
        "award_amount": award_amount,
        "deadline": deadline,
        "eligibility": eligibility,
        "disciplines": disciplines or [],
        "org_types": org_types or [],
        "location": location,
        "source": source,
    }


def _parse_grants_gov_date(date_str: str | None) -> str | None:
    """Convert MM/DD/YYYY to ISO YYYY-MM-DD."""
    if not date_str:
        return None
    try:
        parts = date_str.strip().split("/")
        if len(parts) == 3:
            return f"{parts[2]}-{parts[0].zfill(2)}-{parts[1].zfill(2)}"
    except Exception:
        pass
    return date_str


def _extract_funder_from_url(url: str, displayed_link: str) -> str:
    """Best-effort funder name from URL domain."""
    try:
        import urllib.parse
        host = urllib.parse.urlparse(url).hostname or ""
        host = host.replace("www.", "")
        return displayed_link.split("/")[0] if displayed_link else host
    except Exception:
        return "Unknown"


# ---------------------------------------------------------------------------
# Grants.gov REST API (free, no key required)
# ---------------------------------------------------------------------------

def fetch_grants_gov(keywords: list[str], disciplines: list[str] | None = None) -> list[dict]:
    """Search Grants.gov for open opportunities matching keywords."""
    grants = []
    seen: set[str] = set()

    for keyword in keywords:
        try:
            response = requests.post(
                "https://apply07.grants.gov/grantsws/rest/opportunities/search/",
                json={
                    "keyword": keyword,
                    "oppStatuses": "posted",
                    "rows": 25,
                    "startRecordNum": 0,
                },
                headers={"Content-Type": "application/json"},
                timeout=20,
            )
            response.raise_for_status()
            data = response.json()
        except Exception as e:
            print(f"Grants.gov error for '{keyword}': {e}")
            continue

        hits = data.get("oppHits") or []
        if not isinstance(hits, list):
            continue

        for hit in hits:
            if not isinstance(hit, dict):
                continue
            title = hit.get("title") or ""
            funder = hit.get("agencyName") or "Federal Agency"
            key = f"{title.lower()}|{funder.lower()}"
            if key in seen:
                continue
            seen.add(key)

            award_floor = hit.get("awardFloor") or 0
            award_ceiling = hit.get("awardCeiling") or 0
            if award_floor and award_ceiling:
                award_amount = f"${award_floor:,} – ${award_ceiling:,}"
            elif award_ceiling:
                award_amount = f"Up to ${award_ceiling:,}"
            elif award_floor:
                award_amount = f"From ${award_floor:,}"
            else:
                award_amount = None

            app_types = [
                a.get("description", "") for a in (hit.get("applicantTypes") or [])
                if isinstance(a, dict)
            ]

            opp_id = hit.get("id") or hit.get("number") or ""
            url = f"https://www.grants.gov/search-results-detail/{opp_id}" if opp_id else "https://www.grants.gov"

            grants.append(_grant_shape(
                funder=funder,
                title=title,
                description=hit.get("synopsisDesc") or "",
                url=url,
                award_amount=award_amount,
                deadline=_parse_grants_gov_date(hit.get("closeDate")),
                eligibility=", ".join(app_types) if app_types else None,
                org_types=_map_applicant_types(app_types),
                location="National",
                source="grants_gov",
            ))

        print(f"Grants.gov: {len(hits)} hits for '{keyword}'")

    return grants


def _map_applicant_types(types: list[str]) -> list[str]:
    """Map Grants.gov applicant type labels to our simplified org_types."""
    mapped = []
    lower = " ".join(t.lower() for t in types)
    if "individual" in lower or "artist" in lower:
        mapped.append("individual")
    if "nonprofit" in lower or "501" in lower or "private institution" in lower:
        mapped.append("nonprofit")
    if "state" in lower or "local" in lower or "government" in lower:
        mapped.append("government")
    if "tribal" in lower:
        mapped.append("tribal")
    return mapped or ["unclear"]


# ---------------------------------------------------------------------------
# SerpAPI — grant-specific web search
# ---------------------------------------------------------------------------

def fetch_serpapi_grants(keyword: str, discipline: str = "", location: str = "") -> list[dict]:
    api_key = os.getenv("SERPAPI_API_KEY")
    if not api_key:
        print("SERPAPI_API_KEY not set")
        return []

    q = keyword
    if discipline:
        q = f"{discipline} {q}"
    if location and location.lower() not in ("national", "remote", ""):
        q = f"{q} {location}"

    try:
        search = GoogleSearch({
            "engine": "google",
            "q": q,
            "hl": "en",
            "num": 10,
            "api_key": api_key,
        })
        results = search.get_dict()
    except Exception as e:
        print(f"SerpAPI grant search error for '{q}': {e}")
        return []

    grants = []
    for result in results.get("organic_results", []):
        link = result.get("link") or ""
        grants.append(_grant_shape(
            funder=_extract_funder_from_url(link, result.get("displayed_link") or ""),
            title=result.get("title") or "",
            description=result.get("snippet") or "",
            url=link,
            source="serpapi",
        ))

    return grants


# ---------------------------------------------------------------------------
# Serper.dev — fallback web search
# ---------------------------------------------------------------------------

def fetch_serper_grants(keyword: str) -> list[dict]:
    api_key = os.getenv("SERPER_API_KEY")
    if not api_key:
        print("SERPER_API_KEY not set")
        return []

    try:
        response = requests.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
            json={"q": keyword},
            timeout=15,
        )
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        print(f"Serper.dev error for '{keyword}': {e}")
        return []

    grants = []
    for result in data.get("organic", []):
        link = result.get("link") or ""
        grants.append(_grant_shape(
            funder=_extract_funder_from_url(link, result.get("displayedLink") or ""),
            title=result.get("title") or "",
            description=result.get("snippet") or "",
            url=link,
            source="serper",
        ))

    return grants


# ---------------------------------------------------------------------------
# NYFA Source scraper
# ---------------------------------------------------------------------------

def fetch_nyfa_source() -> list[dict]:
    """Scrape NYFA Source grant listings."""
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        print("beautifulsoup4 not installed — skipping NYFA Source")
        return []

    url = "https://www.nyfa.org/opportunities/?type=Grant"
    try:
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
        resp.raise_for_status()
    except Exception as e:
        print(f"NYFA Source scrape error: {e}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    grants = []

    for card in soup.select(".opportunity-card, .listing-item, article.post"):
        try:
            title_el = card.select_one("h2, h3, .title, .opportunity-title")
            title = title_el.get_text(strip=True) if title_el else ""
            if not title:
                continue

            link_el = card.select_one("a")
            link = link_el["href"] if link_el and link_el.get("href") else url
            if link.startswith("/"):
                link = f"https://www.nyfa.org{link}"

            desc_el = card.select_one("p, .description, .excerpt")
            desc = desc_el.get_text(strip=True) if desc_el else ""

            deadline_el = card.select_one(".deadline, .date, time")
            deadline_text = deadline_el.get_text(strip=True) if deadline_el else None

            funder_el = card.select_one(".funder, .organization, .sponsor")
            funder = funder_el.get_text(strip=True) if funder_el else "NYFA Source"

            grants.append(_grant_shape(
                funder=funder, title=title, description=desc,
                url=link, deadline=deadline_text, source="nyfa_source",
            ))
        except Exception:
            continue

    print(f"NYFA Source: {len(grants)} grants")
    return grants


# ---------------------------------------------------------------------------
# Unrestricted Funds scraper
# ---------------------------------------------------------------------------

def fetch_unrestricted_funds() -> list[dict]:
    """Scrape Unrestricted Funds grant listings."""
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        print("beautifulsoup4 not installed — skipping Unrestricted Funds")
        return []

    base_url = "https://unrestrictedfunds.com"
    try:
        resp = requests.get(base_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
        resp.raise_for_status()
    except Exception as e:
        print(f"Unrestricted Funds scrape error: {e}")
        return []

    from bs4 import BeautifulSoup
    soup = BeautifulSoup(resp.text, "html.parser")
    grants = []

    for card in soup.select("article, .grant-item, .entry, .post"):
        try:
            title_el = card.select_one("h1, h2, h3, .entry-title, .grant-title")
            title = title_el.get_text(strip=True) if title_el else ""
            if not title:
                continue

            link_el = card.select_one("a")
            link = link_el["href"] if link_el and link_el.get("href") else base_url
            if link.startswith("/"):
                link = f"{base_url}{link}"

            desc_el = card.select_one("p, .entry-content, .excerpt, .summary")
            desc = desc_el.get_text(strip=True) if desc_el else ""

            deadline_el = card.select_one(".deadline, .due-date, time")
            deadline_text = deadline_el.get_text(strip=True) if deadline_el else "Rolling"

            amount_el = card.select_one(".amount, .award, .grant-amount")
            award_amount = amount_el.get_text(strip=True) if amount_el else None

            grants.append(_grant_shape(
                funder="Unrestricted Funds",
                title=title, description=desc, url=link,
                award_amount=award_amount, deadline=deadline_text,
                source="unrestricted_funds",
            ))
        except Exception:
            continue

    print(f"Unrestricted Funds: {len(grants)} grants")
    return grants


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

def fetch_all_grants(user_config) -> list[dict]:
    """
    Fetch grants from all sources for a given user config.
    Deduplicates by title+funder (case-insensitive).
    """
    grants: list[dict] = []
    keywords = user_config.keywords or []
    disciplines = user_config.disciplines or []
    location = user_config.location_pref or ""

    print("🔍 GRANT SEARCH START")

    # 1. Grants.gov — structured federal API (free)
    gov_grants = fetch_grants_gov(keywords, disciplines=disciplines)
    print(f"Grants.gov total: {len(gov_grants)}")
    grants.extend(gov_grants)

    # 2. SerpAPI per keyword + discipline combo; Serper as fallback
    for keyword in keywords:
        for discipline in (disciplines[:2] if disciplines else [""]):
            serpapi_results = fetch_serpapi_grants(keyword, discipline=discipline, location=location)
            if serpapi_results:
                print(f"SerpAPI: {len(serpapi_results)} grants for '{discipline} {keyword}'")
                grants.extend(serpapi_results)
            else:
                query = f"{discipline} {keyword} open grant applications 2026".strip()
                serper_results = fetch_serper_grants(query)
                print(f"Serper.dev: {len(serper_results)} grants for '{query}'")
                grants.extend(serper_results)

    # 3. NYFA Source — curated artist opportunities (run once)
    grants.extend(fetch_nyfa_source())

    # 4. Unrestricted Funds — curated unrestricted grants (run once)
    grants.extend(fetch_unrestricted_funds())

    print(f"Total grants collected (pre-dedup): {len(grants)}")

    # Deduplicate by title+funder
    seen_keys: set[str] = set()
    deduped: list[dict] = []
    for grant in grants:
        title = (grant.get("title") or "").lower().strip()
        funder = (grant.get("funder") or "").lower().strip()
        key = f"{title}|{funder}"
        if key in seen_keys or not title:
            continue
        seen_keys.add(key)
        deduped.append(grant)

    print(f"After deduplication: {len(deduped)} grants")
    return deduped
