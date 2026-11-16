"""Owner-input opportunity prioritization; never a sales or profit forecast.

Scores operational fit only from comparable, explicitly supplied assessments.
Unknown fields stay unknown and are excluded from the fit score.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


LEGAL_POLICY_STATES = {
    "not_assessed",
    "review_needed",
    "owner_reviewed_no_blocker",
    "concern_identified",
}


@dataclass(frozen=True)
class OperationalAssessment:
    currency: str
    startup_cost_minor: int
    ongoing_cost_minor: int | None = None
    hours_to_first_delivery: float | None = None
    delivery_complexity: int | None = None
    fulfillment_burden: int | None = None
    legal_policy_status: str = "not_assessed"

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "OperationalAssessment":
        if not isinstance(raw, dict):
            raise ValueError("assessment must be an object")
        currency = str(raw.get("currency", "USD")).upper()
        if len(currency) != 3 or not currency.isalpha():
            raise ValueError("currency must be a three-letter code")
        startup = raw.get("startup_cost_minor")
        if isinstance(startup, bool) or not isinstance(startup, int) or startup < 0:
            raise ValueError("startup_cost_minor must be a non-negative integer supplied by the owner")
        ongoing = raw.get("ongoing_cost_minor")
        if ongoing is not None and (isinstance(ongoing, bool) or not isinstance(ongoing, int) or ongoing < 0):
            raise ValueError("ongoing_cost_minor must be a non-negative integer or null")
        hours = raw.get("hours_to_first_delivery")
        if hours is not None and (isinstance(hours, bool) or not isinstance(hours, (int, float)) or hours < 0):
            raise ValueError("hours_to_first_delivery must be a non-negative number or null")
        complexity = raw.get("delivery_complexity")
        burden = raw.get("fulfillment_burden")
        for name, value in (("delivery_complexity", complexity), ("fulfillment_burden", burden)):
            if value is not None and (isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 5):
                raise ValueError(f"{name} must be an integer from 1 to 5 or null")
        legal = raw.get("legal_policy_status", "not_assessed")
        if legal not in LEGAL_POLICY_STATES:
            raise ValueError("legal_policy_status must be one of: " + ", ".join(sorted(LEGAL_POLICY_STATES)))
        return cls(currency, startup, ongoing, float(hours) if hours is not None else None,
                   complexity, burden, legal)


def prioritize_opportunities(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rank comparable assessments by relative operational fit, with unknowns visible."""
    if not isinstance(items, list):
        raise ValueError("input JSON must be a list")
    prepared = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError(f"item {index} must be an object")
        dossier = item.get("dossier", item)
        if not isinstance(dossier, dict):
            raise ValueError(f"item {index} dossier must be an object")
        opportunity = dossier.get("opportunity", {})
        if not isinstance(opportunity, dict):
            raise ValueError(f"item {index} opportunity must be an object")
        title = opportunity.get("title") or item.get("title") or f"Opportunity {index + 1}"
        assessment_raw = item.get("assessment")
        if assessment_raw is None:
            raise ValueError(f"{title}: assessment object is required")
        assessment = OperationalAssessment.from_dict(assessment_raw)
        prepared.append((title, dossier, assessment))

    # Cost and time are ranked only against entries using the same currency.
    groups: dict[str, list[int]] = {}
    for i, (_, _, a) in enumerate(prepared):
        groups.setdefault(a.currency, []).append(i)

    cost_scores: dict[int, int] = {}
    time_scores: dict[int, int] = {}
    for indices in groups.values():
        known_costs = [(i, prepared[i][2].startup_cost_minor +
                        (prepared[i][2].ongoing_cost_minor or 0))
                       for i in indices if prepared[i][2].ongoing_cost_minor is not None]
        if known_costs:
            ordered = sorted(v for _, v in known_costs)
            for i, value in known_costs:
                cost_scores[i] = 20 if len(ordered) == 1 else round(20 * (len(ordered) - ordered.index(value)) / len(ordered))
        known_times = [(i, prepared[i][2].hours_to_first_delivery)
                       for i in indices if prepared[i][2].hours_to_first_delivery is not None]
        if known_times:
            ordered_times = sorted(v for _, v in known_times)
            for i, value in known_times:
                time_scores[i] = 20 if len(ordered_times) == 1 else round(20 * (len(ordered_times) - ordered_times.index(value)) / len(ordered_times))

    results = []
    for i, (title, dossier, a) in enumerate(prepared):
        components: dict[str, int] = {}
        missing: list[str] = []
        if a.ongoing_cost_minor is None:
            missing.append("ongoing_cost_minor")
        else:
            components["cost"] = cost_scores[i]
        if a.hours_to_first_delivery is None:
            missing.append("hours_to_first_delivery")
        else:
            components["time_to_first_delivery"] = time_scores[i]
        if a.delivery_complexity is None:
            missing.append("delivery_complexity")
        else:
            components["delivery_complexity"] = (5 - a.delivery_complexity) * 5
        if a.fulfillment_burden is None:
            missing.append("fulfillment_burden")
        else:
            components["fulfillment_burden"] = (5 - a.fulfillment_burden) * 5
        legal_scores = {
            "owner_reviewed_no_blocker": 20,
            "review_needed": 10,
            "not_assessed": 0,
            "concern_identified": 0,
        }
        components["legal_policy_review"] = legal_scores[a.legal_policy_status]
        if a.legal_policy_status == "not_assessed":
            missing.append("legal_policy_status")
        score = round(sum(components.values()) / len(components)) if components else 0
        validation = dossier.get("validation", {})
        results.append({
            "title": title,
            "currency": a.currency,
            "operational_fit_score": score,
            "score_label": "relative_operational_fit_from_owner_inputs",
            "score_components": components,
            "assessment_completeness": round(100 * (5 - len(missing)) / 5),
            "missing_information": missing,
            "owner_inputs": {
                "startup_cost_minor": a.startup_cost_minor,
                "ongoing_cost_minor": a.ongoing_cost_minor,
                "hours_to_first_delivery": a.hours_to_first_delivery,
                "delivery_complexity_1_to_5": a.delivery_complexity,
                "fulfillment_burden_1_to_5": a.fulfillment_burden,
                "legal_policy_status": a.legal_policy_status,
            },
            "research_validation_status": validation.get("status", "unknown"),
            "research_blockers": validation.get("blockers", []),
            "recommended_next_steps": [
                f"Supply or verify: {field}" for field in missing
            ] + (["Review legal and marketplace policies with qualified sources; this tool makes no legal determination."]
                 if a.legal_policy_status != "owner_reviewed_no_blocker" else []),
            "can_publish": False,
            "can_spend": False,
            "sales_verified": False,
            "profitability_verified": False,
            "warning": "This is a relative operational-fit aid based only on owner-supplied inputs. It is not a demand, sales, profit, legal-compliance, or commercial-approval prediction.",
        })
    return sorted(results, key=lambda row: (-row["operational_fit_score"], -row["assessment_completeness"], row["title"].casefold()))
