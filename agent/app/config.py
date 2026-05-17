"""Local fallback config — used only for --mock --dry-run when DATABASE_URL is not set.
Real user profiles are always loaded from Postgres via get_user_config(user_id).
"""

PROFILE = {
    "name": "Test Artist",
    "disciplines": ["visual art", "community organizing"],
    "org_type": "individual",
    "location": "New York, NY",
    "geographic_focus": ["NYC", "New York State", "national"],
    "project_description": "Interdisciplinary visual artist working with installation and public art.",
    "past_grants": "",
    "constraints": "",
    "summary": "Visual artist and community organizer based in NYC seeking grants for project development and community programming.",
    "budget_min": 1000,
    "deadline_window_days": 90,
    "scoring_weights": {"mission": "high", "award": "medium", "deadline": "medium"},
}

KEYWORDS = [
    "visual art grants",
    "artist fellowship",
    "community arts funding",
]
