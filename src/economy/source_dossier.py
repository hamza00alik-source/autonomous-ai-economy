"""Compile owner-reviewed source notes into a conservative opportunity dossier.

Reviewed source classifications are kept separate from validated evidence. All
compiled Evidence records are marked non-independent, so the existing validator
cannot mistake this dossier for corroborated buyer demand.
"""
from __future__ import annotations

from datetime import date
from typing import Iterable

from .opportunities import Evidence, EvidenceKind, Opportunity, OpportunityValidator
from .source_review import SourceReviewStore

_CLASSIFICATION_TO_KIND = {
    "supports_buyer_problem": EvidenceKind.BUYER_SIGNAL,
    "competitor_offer": EvidenceKind.COMPETITOR,
    "cost_reference": EvidenceKind.COST,
    "legal_policy_reference": EvidenceKind.LEGAL_OR_POLICY,
    "market_context": EvidenceKind.MARKET_CONTEXT,
}


def _observed_date(review: dict) -> str:
    snapshot = review.get("snapshot", {})
    value = snapshot.get("fetched_at") or snapshot.get("retrieved_at") or review.get("reviewed_at", "")
    try:
        return date.fromisoformat(str(value)[:10]).isoformat()
    except ValueError:
        return str(review.get("reviewed_at", ""))[:10] or date.today().isoformat()


def build_source_dossier(
    store: SourceReviewStore,
    *,
    title: str,
    buyer_segment: str,
    problem: str,
    proposed_solution: str,
    delivery_format: str,
    estimated_startup_cost_minor: int,
    currency: str = "USD",
    legal_risk_notes: str = "",
) -> dict:
    """Build a draft dossier; reviewed notes are never independent evidence."""
    reviews = store.list_reviews()
    evidence: list[Evidence] = []
    included_reviews: list[dict] = []
    excluded_reviews: list[dict] = []
    for review in reviews:
        classification = review["classification"]
        kind = _CLASSIFICATION_TO_KIND.get(classification)
        if kind is None:
            excluded_reviews.append({
                "review_id": review["review_id"],
                "classification": classification,
                "reason": "not relevant or marked unreliable; excluded from evidence candidates",
            })
            continue
        evidence.append(Evidence(
            source_name=review["publisher_identity"],
            url=review["source_url"],
            observed_on=_observed_date(review),
            kind=kind,
            finding=review["finding"],
            independent_source=False,
        ))
        included_reviews.append({
            "review_id": review["review_id"],
            "source_url": review["source_url"],
            "publisher_identity": review["publisher_identity"],
            "content_sha256": review["content_sha256"],
            "classification": classification,
            "finding": review["finding"],
            "reviewer_note": review["reviewer_note"],
            "independent_source": False,
        })

    opportunity = Opportunity(
        title=title,
        buyer_segment=buyer_segment,
        problem=problem,
        proposed_solution=proposed_solution,
        delivery_format=delivery_format,
        estimated_startup_cost_minor=estimated_startup_cost_minor,
        currency=currency,
        legal_risk_notes=legal_risk_notes,
        evidence=tuple(evidence),
    )
    report = OpportunityValidator().evaluate(opportunity)
    dossier = {
        "schema_version": 1,
        "dossier_type": "owner_reviewed_research_draft",
        "opportunity": {
            "title": opportunity.title,
            "buyer_segment": opportunity.buyer_segment,
            "problem": opportunity.problem,
            "proposed_solution": opportunity.proposed_solution,
            "delivery_format": opportunity.delivery_format,
            "estimated_startup_cost_minor": opportunity.estimated_startup_cost_minor,
            "currency": opportunity.currency,
            "legal_risk_notes": opportunity.legal_risk_notes,
            "evidence": [{
                "source_name": item.source_name,
                "url": item.url,
                "observed_on": item.observed_on,
                "kind": item.kind.value,
                "finding": item.finding,
                "independent_source": False,
            } for item in evidence],
        },
        "source_reviews": included_reviews,
        "excluded_source_reviews": excluded_reviews,
        "validation": report.to_dict(),
        "readiness": {
            "status": report.status.value,
            "owner_review_required": True,
            "can_publish": False,
            "can_spend": False,
            "real_buyer_demand_verified": False,
            "sales_verified": False,
            "profitability_verified": False,
        },
        "required_next_steps": [
            "Independently verify the identity and provenance of each publisher.",
            "Find direct buyer evidence; owner-reviewed articles or discussions alone do not prove willingness to pay.",
            "Check whether any sources are syndicated, related, or otherwise non-independent.",
            "Add independently verified cost and legal/policy references.",
            "Complete written risk assessment and unit-economics scenarios.",
            "Submit the dossier for explicit owner review; do not publish or spend from this draft.",
        ],
        "notice": "Draft research dossier only. Owner classifications are not fact-checked. Every compiled evidence candidate is marked independent_source=false and cannot satisfy the independent evidence gate.",
    }
    return dossier
