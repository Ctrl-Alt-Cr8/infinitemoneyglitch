"""Grant relevance scoring powered by Claude Haiku."""

from __future__ import annotations

import json

from app.utils.claude_client import call_claude_haiku


DEFAULT_SCORE = {
    "score": 0,
    "eligibility_status": "unclear",
    "why_fit": "Unable to score this grant right now.",
    "mission_alignment": "Could not evaluate.",
    "gaps": "Could not evaluate gaps.",
}


def _extract_json_payload(raw_text: str) -> str:
    text = raw_text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].strip()
    return text


def _weights_to_instruction(weights: dict) -> str:
    """Convert High/Medium/Low weights to scoring instruction text."""
    lines = []
    mapping = {"high": "heavily", "medium": "moderately", "low": "lightly"}
    for criterion, level in (weights or {}).items():
        word = mapping.get((level or "").lower(), "moderately")
        lines.append(f"- {criterion.replace('_', ' ').title()}: weight {word}")
    return "\n".join(lines) if lines else "- Weight all criteria equally"


def score_grant(grant: dict, profile: dict, eligibility_status: str = "unclear") -> dict:
    """Score a single grant against the user's profile using Claude Haiku."""
    weights = profile.get("scoring_weights") or {}
    weight_instruction = _weights_to_instruction(weights)

    prompt = f"""
You are evaluating grant relevance for an artist or community organizer.

Eligibility pre-check: {eligibility_status}
(eligible = confirmed eligible | likely = eligible via fiscal sponsor or probable | unclear = unknown | ineligible = blocked)

Applicant profile:
{json.dumps(profile, indent=2)}

Grant:
{json.dumps(grant, indent=2)}

Scoring priorities (user-defined):
{weight_instruction}

Scoring rules:
- Eligibility is the primary gate. If eligibility_status is "ineligible", score 0-15 regardless of fit.
- If "unclear" or "likely", use your best judgment based on the grant description.
- If "eligible", score purely on fit and alignment.
- Weight criteria as instructed above.
- Be honest about gaps — a high score means the applicant should seriously pursue this.

Return VALID JSON ONLY:
{{
  "score": number (0-100),
  "eligibility_status": "eligible" | "likely" | "unclear" | "ineligible",
  "why_fit": string (concise, specific — why this grant matches this applicant),
  "mission_alignment": string (how the grant's mission matches the applicant's work),
  "gaps": string (honest, brief — what might disqualify or weaken the application)
}}

No markdown, no code fences, no extra keys.
""".strip()

    try:
        response_text = call_claude_haiku(prompt)
        payload = _extract_json_payload(response_text)
        parsed = json.loads(payload)

        required_keys = {"score", "eligibility_status", "why_fit", "mission_alignment", "gaps"}
        if not required_keys.issubset(parsed):
            return DEFAULT_SCORE

        parsed["score"] = max(0, min(100, int(float(parsed["score"]))))
        return parsed
    except Exception as e:
        print(f"Claude scoring error: {e}")
        return DEFAULT_SCORE


def score_grants_batch(grants: list[dict], profile: dict, eligibility_map: dict[int, str] | None = None) -> list[dict]:
    """
    Score all grants using chunked Claude Haiku calls (8 per call).
    Falls back to individual scoring for any chunk that fails.
    eligibility_map: {grant_index: eligibility_status} from pre-filter step.
    """
    if not grants:
        return []

    if eligibility_map is None:
        eligibility_map = {}

    CHUNK_SIZE = 8
    all_results: list[dict] = []
    chunks = [grants[i:i + CHUNK_SIZE] for i in range(0, len(grants), CHUNK_SIZE)]
    weights = profile.get("scoring_weights") or {}
    weight_instruction = _weights_to_instruction(weights)

    print(f"Scoring {len(grants)} grants in {len(chunks)} chunks of up to {CHUNK_SIZE}")

    for chunk_index, chunk in enumerate(chunks):
        base_index = chunk_index * CHUNK_SIZE
        grants_payload = [
            {
                "index": i,
                "eligibility_status": eligibility_map.get(base_index + i, "unclear"),
                "grant": g,
            }
            for i, g in enumerate(chunk)
        ]

        prompt = f"""
You are evaluating grant relevance for an artist or community organizer.

Applicant profile:
{json.dumps(profile, indent=2)}

Scoring priorities (user-defined):
{weight_instruction}

Scoring rules:
- Eligibility is the primary gate. Each grant includes its pre-checked eligibility_status.
  - "ineligible" → score 0-15 regardless of fit
  - "unclear" or "likely" → use your best judgment
  - "eligible" → score on pure fit and alignment
- Weight the criteria as instructed above.
- Be honest about gaps.

Below are {len(chunk)} grants. Return a JSON array with exactly {len(chunk)} objects in input order.

Each object must have exactly:
{{
  "score": number (0-100),
  "eligibility_status": "eligible" | "likely" | "unclear" | "ineligible",
  "why_fit": string,
  "mission_alignment": string,
  "gaps": string
}}

Grants:
{json.dumps(grants_payload, indent=2)}

Return ONLY a valid JSON array. No markdown, no code fences, no preamble, no extra keys.
""".strip()

        try:
            response_text = call_claude_haiku(prompt)
            payload = _extract_json_payload(response_text)
            parsed_list = json.loads(payload)

            if not isinstance(parsed_list, list) or len(parsed_list) != len(chunk):
                raise ValueError(
                    f"Expected {len(chunk)} results, got "
                    f"{len(parsed_list) if isinstance(parsed_list, list) else 'non-list'}"
                )

            required_keys = {"score", "eligibility_status", "why_fit", "mission_alignment", "gaps"}
            for i, parsed in enumerate(parsed_list):
                if not required_keys.issubset(parsed):
                    print(f"Chunk {chunk_index} grant {i} missing keys, using default score")
                    all_results.append(DEFAULT_SCORE)
                    continue
                parsed["score"] = max(0, min(100, int(float(parsed["score"]))))
                all_results.append(parsed)

            print(f"Chunk {chunk_index + 1}/{len(chunks)} scored ({len(chunk)} grants)")

        except Exception as e:
            print(f"Chunk {chunk_index + 1} failed ({e}), falling back to individual scoring")
            for i, grant in enumerate(chunk):
                eligibility = eligibility_map.get(base_index + i, "unclear")
                all_results.append(score_grant(grant, profile, eligibility_status=eligibility))

    print(f"Batch complete: scored {len(all_results)} grants in {len(chunks)} Claude calls")
    return all_results
