"""Conservative rule-element assessment. No driver names or race IDs in policy."""

from __future__ import annotations

from .contracts import CaseInput, Condition, ModelReview, now_iso
from .rulebook import rulebook_hash, search_rules

POLICY_VERSION = "evidence-v1"
COLLISION_ELEMENTS = [
    "contact",
    "inside_overtake",
    "overlap_prior_and_apex",
    "controlled",
    "other_driver_contributed",
    "external_cause",
    "mitigating_circumstances",
    "reckless_or_deliberate",
    "sporting_consequence",
]
TRACK_ELEMENTS = [
    "left_track",
    "forced_off",
    "collision_avoidance",
    "lasting_advantage",
    "advantage_returned",
]


def condition(case: CaseInput, predicate: str) -> Condition:
    # Public telemetry cannot substantiate spatial/legal propositions, even if
    # the sender calls an estimate "verified".
    evidence = [
        e for e in case.observations if e.predicate == predicate and e.verified and e.source != "telemetry"
    ]
    values = {e.value for e in evidence}
    status = (
        "conflicting"
        if len(values) > 1
        else "supported"
        if values == {True}
        else "contradicted"
        if values == {False}
        else "unknown"
    )
    return Condition(predicate=predicate, status=status, evidence_ids=[e.id for e in evidence])


def assess(case: CaseInput) -> dict:
    rules = search_rules(case.event_date, case.incident_type, case.incident_type)
    predicates = (
        COLLISION_ELEMENTS
        if case.incident_type == "collision"
        else TRACK_ELEMENTS
        if case.incident_type == "off_track"
        else []
    )
    conditions = [condition(case, p) for p in predicates]
    statuses = {c.predicate: c.status for c in conditions}
    missing = [c.predicate for c in conditions if c.status == "unknown"]
    ruling, seconds = "INSUFFICIENT_EVIDENCE", None
    summary = "Available evidence cannot establish an offence or responsibility."
    alternative = "Normal racing, another driver's contribution or an external cause remain possible."

    def true(p):
        return statuses.get(p) == "supported"

    def false(p):
        return statuses.get(p) == "contradicted"

    if not rules:
        missing.append("reviewed rules applicable to this event and incident type")
        summary = "No reviewed rule bundle covers this event and incident type. Manual review is required."
    elif case.session_type != "R":
        ruling = "REVIEW_REQUIRED"
        summary = "The implemented sanction policy covers races only; this session requires manual review."
    elif any(c.status == "conflicting" for c in conditions):
        ruling = "REVIEW_REQUIRED"
        summary = "Verified observations conflict; resolve the evidence before deciding."
    elif case.incident_type == "collision":
        if false("contact"):
            ruling = "NO_FURTHER_ACTION"
            summary = "Verified evidence contradicts contact; the alleged collision is not established."
            alternative = "A near miss or close racing explains the candidate event."
        elif true("other_driver_contributed") or true("external_cause"):
            ruling = "REVIEW_REQUIRED"
            summary = "Shared contribution or an external cause requires responsibility review."
        elif not missing:
            if (
                true("inside_overtake")
                and false("overlap_prior_and_apex")
                and false("controlled")
                and true("contact")
            ):
                if true("reckless_or_deliberate") or false("sporting_consequence"):
                    ruling = "REVIEW_REQUIRED"
                    summary = (
                        "The offence is supported, but this sanction category requires manual assessment."
                    )
                else:
                    ruling = "PENALTY_RECOMMENDED"
                    seconds = 5 if true("mitigating_circumstances") else 10
                    summary = f"Inside attempt without required overlap and control resulted in contact. Recommend {seconds} seconds under the applicable collision guidance."
                    alternative = "Shared responsibility and an external cause were checked and contradicted by the supplied reviewed evidence."
            else:
                ruling = "REVIEW_REQUIRED"
                summary = "This collision does not satisfy the implemented inside-overtake pattern; assess other responsibility patterns manually."
    elif case.incident_type == "off_track":
        if false("left_track"):
            ruling = "NO_FURTHER_ACTION"
            summary = "Verified evidence contradicts the alleged track excursion."
        elif (
            true("left_track")
            and (true("forced_off") or true("collision_avoidance"))
            and (false("lasting_advantage") or true("advantage_returned"))
        ):
            ruling = "NO_FURTHER_ACTION"
            summary = "Reviewed evidence supports an avoidance/forced-off exception without a retained advantage. This does not assess a separate unsafe rejoin."
            alternative = "The excursion was justified under the reviewed exception."
        elif not missing:
            ruling = "REVIEW_REQUIRED"
            summary = "Review track-limit history, session procedures and sanction context before assigning a penalty."

    return {
        **case.model_dump(mode="json"),
        "ruling": ruling,
        "penalty_seconds": seconds,
        "penalty_points": None,
        "summary": summary,
        "alternative_explanation": alternative,
        "conditions": [c.model_dump() for c in conditions],
        "missing_facts": missing,
        "rules": rules,
        "confidence_score": None,
        "policy_version": POLICY_VERSION,
        "rulebook_hash": rulebook_hash(rules),
        "assessed_at": now_iso(),
        "model_review": {"status": "disabled"},
    }


def apply_model_review(result: dict, review: ModelReview) -> dict:
    """A model can request scrutiny, never manufacture facts or promote guilt."""
    allowed_rules = {r["id"] for r in result["rules"]}
    if not review.rule_ids or not set(review.rule_ids) <= allowed_rules:
        raise ValueError("Model cited a rule outside the applicable bundle")
    original = {c["predicate"]: c for c in result["conditions"]}
    if len(review.conditions) != len(original) or {c.predicate for c in review.conditions} != set(original):
        raise ValueError("Model must assess every supplied condition exactly once")
    disagreement = False
    for c in review.conditions:
        expected = original[c.predicate]
        if not set(c.evidence_ids) <= set(expected["evidence_ids"]):
            raise ValueError("Model cited unsupported evidence for a condition")
        if c.status in {"supported", "contradicted", "conflicting"} and not c.evidence_ids:
            raise ValueError("Model asserted a fact without evidence")
        if c.status != expected["status"]:
            disagreement = True
    updated = {**result, "model_review": {"status": "reviewed", **review.model_dump()}}
    if disagreement or review.missing_facts:
        updated.update(
            ruling="REVIEW_REQUIRED",
            penalty_seconds=None,
            summary="Model review identified uncertainty or disagreement. Resolve the cited conditions before deciding.",
        )
    return updated
