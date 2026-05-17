"""On-demand LOI and artist statement generation — called only from /draft-document endpoint."""

from __future__ import annotations

import json
import re

from app.utils.claude_client import call_claude_sonnet


def _word_count(text: str) -> int:
    return len(text.split())


def validate_loi(text: str) -> dict:
    issues = []

    wc = _word_count(text)
    if wc < 200:
        issues.append(f"Too short ({wc} words — minimum 200)")
    elif wc > 500:
        issues.append(f"Too long ({wc} words — maximum 500)")

    banned_phrases = [
        "i am passionate about",
        "i'm passionate about",
        "i am excited to",
        "i'm excited to",
        "i believe i am",
        "i believe i'm",
        "please consider",
        "i humbly",
        "i would be honored",
        "team player",
        "hardworking",
    ]
    text_lower = text.lower()
    for phrase in banned_phrases:
        if phrase in text_lower:
            issues.append(f"Banned phrase: '{phrase}'")

    em_dashes = len(re.findall(r"—", text))
    if em_dashes > 2:
        issues.append(f"Too many em dashes ({em_dashes} — max 2)")

    return {"valid": len(issues) == 0, "issues": issues}


def validate_artist_statement(text: str) -> dict:
    issues = []

    wc = _word_count(text)
    if wc < 150:
        issues.append(f"Too short ({wc} words — minimum 150)")
    elif wc > 400:
        issues.append(f"Too long ({wc} words — maximum 400)")

    banned_phrases = [
        "i am passionate about",
        "i'm passionate about",
        "i explore",
        "i strive to",
        "my work seeks to",
        "team player",
        "hardworking",
    ]
    text_lower = text.lower()
    for phrase in banned_phrases:
        if phrase in text_lower:
            issues.append(f"Clichéd phrase: '{phrase}'")

    return {"valid": len(issues) == 0, "issues": issues}


def _build_loi_prompt(grant: dict, profile: dict, retry_issues: list[str] | None = None) -> str:
    retry_block = ""
    if retry_issues:
        retry_block = f"""
IMPORTANT — your previous draft failed validation. Fix ALL of these issues:
{chr(10).join(f'- {issue}' for issue in retry_issues)}

"""

    return f"""
{retry_block}Write a Letter of Intent (LOI) for this grant application.

Applicant profile:
{json.dumps(profile, indent=2)}

Grant:
{json.dumps(grant, indent=2)}

OBJECTIVE:
Write an LOI that is direct, specific, and demonstrates a genuine connection between the applicant's practice and this grant's mission. Do not write a generic application. Show you read the grant guidelines.

TONE:
- Confident and peer-to-peer — the applicant is addressing a funder as a fellow stakeholder in the work, not a supplicant
- No begging, no over-reverence for the funder
- Grounded in the specific project or practice, not vague ambitions
- Professional but not stiff — warm, direct, specific

MANDATORY STRUCTURE (exactly 4 paragraphs, separated by blank lines):
1) Opening: State who the applicant is and what they are applying for. One strong, specific sentence about the project or practice — no preamble, no "I am writing to".
2) Project / practice: Concrete description of the work. What it is, where it exists, who it reaches, what it has accomplished or aims to accomplish.
3) Alignment: Why this grant specifically. Name the funder's mission, program, or stated priority and explain the direct connection to the applicant's work.
4) Close: What the funding would enable. Specific, practical. One or two sentences. No "thank you for your consideration".

STRICT PROHIBITIONS:
- No "I am writing to apply"
- No "I am passionate about"
- No "I believe I am a great fit"
- No "please consider my application"
- No "I humbly"
- No "I would be honored"
- No salary, compensation, or pay references

STYLE:
- Max 2 em dashes (—) in the entire letter
- 200–500 words total
- 4 paragraphs, blank line between each

OUTPUT: Plain text only. No subject line, no greeting, no signature block.
""".strip()


def _build_artist_statement_prompt(profile: dict, grant: dict | None = None, retry_issues: list[str] | None = None) -> str:
    retry_block = ""
    if retry_issues:
        retry_block = f"""
IMPORTANT — your previous draft failed validation. Fix ALL of these issues:
{chr(10).join(f'- {issue}' for issue in retry_issues)}

"""

    grant_context = ""
    if grant:
        grant_context = f"""
Tailor this statement toward the following grant's focus and eligibility:
{json.dumps({"title": grant.get("title"), "funder": grant.get("funder"), "description": (grant.get("description") or "")[:500]}, indent=2)}
"""

    return f"""
{retry_block}Write an artist statement for this applicant.

Applicant profile:
{json.dumps(profile, indent=2)}
{grant_context}

OBJECTIVE:
A clear, specific account of who this artist is, what they make, and why it matters. Not a biography. Not a mission statement. An honest account of the practice.

TONE:
- Present tense, first person
- Specific over general — name actual works, places, collaborators, materials where relevant
- No art-world jargon or vague claims ("interrogates", "explores the tension between", "liminal space")
- Direct and grounded

STRUCTURE (3 paragraphs, blank line between each):
1) What the work is and does — the medium, form, or method. What the audience experiences or encounters.
2) Why this work — the specific problem, question, or community it addresses. What the practice is in response to.
3) Where the work is going — current or next project. What the applicant is developing or pursuing.

STYLE:
- 150–400 words
- 3 paragraphs
- No clichéd phrases: "I am passionate about", "I explore", "I strive to", "my work seeks to"
- Max 2 em dashes

OUTPUT: Plain text only. No title, no heading.
""".strip()


def generate_loi(grant: dict, profile: dict) -> dict:
    """Generate a Letter of Intent for a grant. Two-pass with validation."""
    prompt = _build_loi_prompt(grant, profile)
    try:
        first_draft = call_claude_sonnet(prompt)
    except Exception as e:
        return {"text": "", "valid": False, "issues": [f"Claude error: {e}"]}

    validation = validate_loi(first_draft)
    if validation["valid"]:
        return {"text": first_draft, "valid": True, "issues": []}

    # Second pass with explicit issue list
    retry_prompt = _build_loi_prompt(grant, profile, retry_issues=validation["issues"])
    try:
        second_draft = call_claude_sonnet(retry_prompt)
    except Exception as e:
        return {"text": first_draft, "valid": False, "issues": validation["issues"]}

    final_validation = validate_loi(second_draft)
    return {
        "text": second_draft,
        "valid": final_validation["valid"],
        "issues": final_validation["issues"],
    }


def generate_artist_statement(profile: dict, grant: dict | None = None) -> dict:
    """Generate an artist statement, optionally tailored to a specific grant. Two-pass with validation."""
    prompt = _build_artist_statement_prompt(profile, grant=grant)
    try:
        first_draft = call_claude_sonnet(prompt)
    except Exception as e:
        return {"text": "", "valid": False, "issues": [f"Claude error: {e}"]}

    validation = validate_artist_statement(first_draft)
    if validation["valid"]:
        return {"text": first_draft, "valid": True, "issues": []}

    retry_prompt = _build_artist_statement_prompt(profile, grant=grant, retry_issues=validation["issues"])
    try:
        second_draft = call_claude_sonnet(retry_prompt)
    except Exception as e:
        return {"text": first_draft, "valid": False, "issues": validation["issues"]}

    final_validation = validate_artist_statement(second_draft)
    return {
        "text": second_draft,
        "valid": final_validation["valid"],
        "issues": final_validation["issues"],
    }
