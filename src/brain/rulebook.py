"""Small, reviewed rule bundles; exploratory vector matches never establish law.

All text here is an authored synopsis, not a reproduction of the FIA documents.
Unknown seasons abstain rather than silently borrowing another year's guidance.
"""

from __future__ import annotations

from datetime import date
import hashlib
import json
import re

GUIDELINES = (
    "https://www.fia.com/sites/default/files/f1_driving_standards_guidelines_version_4.1_feb_20_2025.pdf"
)
PENALTIES = (
    "https://www.fia.com/sites/default/files/2025_f1_guidelines_penalty_points_overview_-_14_may_clean_0.pdf"
)

RULES = [
    {
        "id": "2025-driving-A",
        "title": "2025 Driving Standards, section A",
        "authority": "guidance",
        "page": 1,
        "url": GUIDELINES,
        "text": "Inside overtaking entitlement requires the specified front-axle/mirror overlap before and at the apex, controlled driving, a reasonable line and the ability to stay within the track. Assess the full manoeuvre, not one frame.",
        "topics": ["collision", "forced_wide"],
    },
    {
        "id": "2025-driving-context",
        "title": "2025 Driving Standards, context and exceptions",
        "authority": "guidance",
        "page": 2,
        "url": GUIDELINES,
        "text": "Examine how the cars arrived, visibility, available grip, loss of control, corner characteristics and each driver's contribution. Contact alone does not determine responsibility.",
        "topics": ["collision", "forced_wide"],
    },
    {
        "id": "2025-track-limits",
        "title": "2025 Driving Standards, sections D and F / Sporting Article 33.3",
        "authority": "guidance",
        "page": 2,
        "url": GUIDELINES,
        "text": "Track-limit assessment considers justification, collision avoidance, being forced off, safe rejoining and lasting advantage. An opportunity to return an advantage may be given. A track excursion alone does not establish a time penalty.",
        "topics": ["off_track", "forced_wide"],
    },
    {
        "id": "2025-collision-sanction",
        "title": "2025 Penalty Guidelines: causing a collision; Appendix L IV 2(d)",
        "authority": "penalty_guidance",
        "page": 3,
        "url": PENALTIES,
        "text": "For a race collision offence, the recommended baseline is ten seconds. Mitigation can justify five seconds; other circumstances can require different sanctions. Low-consequence incidents and deliberate or reckless conduct have separate treatment. Penalty points require separate assessment.",
        "topics": ["collision"],
    },
]


def applicable_rules(event_date: date, incident_type: str) -> list[dict]:
    # This reviewed bundle uses the May penalty guidance. Do not assert that its
    # sanction policy governed an earlier event, or that it governs 2026.
    if not date(2025, 5, 14) <= event_date <= date(2025, 12, 31):
        return []
    return [
        {**r, "effective_from": "2025-05-14", "effective_to": "2025-12-31"}
        for r in RULES
        if incident_type in r["topics"]
    ]


def rulebook_hash(rules: list[dict]) -> str:
    return hashlib.sha256(json.dumps(rules, sort_keys=True).encode()).hexdigest()


def search_rules(event_date: date, incident_type: str, query: str) -> list[dict]:
    """Rank the complete applicable bundle lexically, retaining exceptions.

    For four reviewed clauses, exhaustive ranking is simpler and safer than top-k
    postfiltering thousands of technical chunks. No truncation or lost exceptions.
    """
    terms = set(re.findall(r"\w+", query.lower()))
    return sorted(
        applicable_rules(event_date, incident_type),
        key=lambda r: -len(terms & set(re.findall(r"\w+", r["text"].lower()))),
    )
