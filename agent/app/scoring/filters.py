"""Grant eligibility and relevance filters — all filtering logic lives here."""

from __future__ import annotations

from datetime import date


def _deadline_is_valid(deadline: str | None, deadline_window_days: int = 90) -> bool:
    """Return True if deadline is in the future and within the user's window."""
    if not deadline:
        return True
    dl = deadline.strip().lower()
    if dl in ("rolling", "ongoing", "open"):
        return True
    try:
        parts = deadline.strip().split("-")
        if len(parts) == 3:
            dl_date = date(int(parts[0]), int(parts[1]), int(parts[2]))
            today = date.today()
            if dl_date < today:
                return False
            return (dl_date - today).days <= deadline_window_days
    except Exception:
        pass
    return True  # Unparseable — pass through to Claude


def _org_type_compatible(grant_org_types: list[str], user_org_type: str) -> str:
    """Returns 'eligible' | 'likely' | 'unclear' | 'ineligible'."""
    if not grant_org_types or "unclear" in grant_org_types:
        return "unclear"

    user = (user_org_type or "individual").lower()
    grant_types = [t.lower() for t in grant_org_types]

    if user == "nonprofit":
        matches = ["nonprofit", "501c3", "organization", "government"]
    elif user == "collective":
        matches = ["nonprofit", "collective", "organization", "individual"]
    else:  # individual
        matches = ["individual", "artist"]

    if any(any(m in g for m in matches) for g in grant_types):
        return "eligible"

    # Individual user + nonprofit-only grant: possible via fiscal sponsorship
    if user == "individual" and any("nonprofit" in g or "organization" in g for g in grant_types):
        return "likely"

    return "ineligible"


def _discipline_relevant(grant: dict, user_disciplines: list[str]) -> bool:
    """True if at least one user discipline appears in the grant text."""
    if not user_disciplines:
        return True
    grant_disciplines = [d.lower() for d in (grant.get("disciplines") or [])]
    combined = " ".join([
        grant.get("description") or "",
        grant.get("eligibility") or "",
        grant.get("title") or "",
        " ".join(grant_disciplines),
    ]).lower()
    for discipline in user_disciplines:
        if any(word in combined for word in discipline.lower().split() if len(word) > 3):
            return True
    return False


def _location_compatible(grant_location: str | None, geographic_focus: list[str]) -> bool:
    """True if grant's geographic scope overlaps with user's focus areas."""
    if not grant_location or not geographic_focus:
        return True
    loc = grant_location.lower()
    if any(kw in loc for kw in ("national", "international", "us-based", "united states")):
        return True
    for focus_area in geographic_focus:
        fa = focus_area.lower()
        if "national" in fa or fa in loc or loc in fa:
            return True
        if len(fa) == 2 and fa in loc:
            return True
    return False


def disqualify_grants(grants: list[dict], config=None) -> list[dict]:
    """Hard-block grants that are definitively ineligible before scoring."""
    filtered = []
    deadline_window = getattr(config, "deadline_window_days", 90) if config else 90
    user_org_type = getattr(config, "org_type", "individual") if config else "individual"

    for grant in grants:
        if not isinstance(grant, dict):
            continue
        if not _deadline_is_valid(grant.get("deadline"), deadline_window):
            print(f"Disqualified (deadline passed): {grant.get('title')}")
            continue
        eligibility_status = _org_type_compatible(grant.get("org_types") or [], user_org_type)
        if eligibility_status == "ineligible":
            print(f"Disqualified (org type mismatch): {grant.get('title')}")
            continue
        filtered.append(grant)

    return filtered


def passes_filters(grant: dict, config=None) -> bool:
    """Soft relevance filter. Drops grants with no discipline match or geo incompatibility."""
    disciplines = getattr(config, "disciplines", []) if config else []
    geographic_focus = getattr(config, "geographic_focus", []) if config else []

    if disciplines and not _discipline_relevant(grant, disciplines):
        return False
    if not _location_compatible(grant.get("location"), geographic_focus):
        print(f"Location filtered ({grant.get('location')}): {grant.get('title')}")
        return False
    return True


def get_eligibility_status(grant: dict, config=None) -> str:
    """Returns eligibility status for injection into the scoring prompt."""
    user_org_type = getattr(config, "org_type", "individual") if config else "individual"
    return _org_type_compatible(grant.get("org_types") or [], user_org_type)
