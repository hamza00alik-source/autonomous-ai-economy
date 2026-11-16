"""Evidence-first opportunity intake and validation.

This module does not perform web research or claim that demand exists. It evaluates
evidence explicitly supplied by a researcher and routes promising candidates to
owner review; it never publishes, spends, or makes customer commitments.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from urllib.parse import urlparse


class EvidenceKind(str, Enum):
    BUYER_SIGNAL = "buyer_signal"
    COMPETITOR = "competitor"
    MARKET_CONTEXT = "market_context"
    LEGAL_OR_POLICY = "legal_or_policy"
    COST = "cost"


class ValidationStatus(str, Enum):
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    NEEDS_RESEARCH = "needs_research"
    OWNER_REVIEW = "owner_review"


@dataclass(frozen=True)
class Evidence:
    source_name: str
    url: str
    observed_on: str
    kind: EvidenceKind
    finding: str
    independent_source: bool = True

    def validate(self) -> list[str]:
        problems: list[str] = []
        parsed = urlparse(self.url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            problems.append("evidence URL must be an absolute http(s) URL")
        if not self.source_name.strip():
            problems.append("evidence source_name is required")
        if not self.finding.strip():
            problems.append("evidence finding is required")
        try:
            date.fromisoformat(self.observed_on)
        except ValueError:
            problems.append("observed_on must be an ISO date (YYYY-MM-DD)")
        return problems


@dataclass(frozen=True)
class Opportunity:
    title: str
    buyer_segment: str
    problem: str
    proposed_solution: str
    delivery_format: str
    estimated_startup_cost_minor: int
    currency: str = "USD"
    legal_risk_notes: str = ""
    evidence: tuple[Evidence, ...] = field(default_factory=tuple)

    def validate(self) -> list[str]:
        problems = []
        for name in ("title", "buyer_segment", "problem", "proposed_solution", "delivery_format"):
            if not getattr(self, name).strip():
                problems.append(f"{name} is required")
        if self.estimated_startup_cost_minor < 0:
            problems.append("estimated_startup_cost_minor cannot be negative")
        if len(self.currency) != 3 or not self.currency.isalpha():
            problems.append("currency must be a three-letter code")
        for index, item in enumerate(self.evidence):
            problems.extend(f"evidence[{index}]: {p}" for p in item.validate())
        return problems


@dataclass(frozen=True)
class ValidationReport:
    status: ValidationStatus
    blockers: tuple[str, ...]
    evidence_count: int
    independent_source_count: int
    owner_approval_required: bool = True
    can_publish: bool = False
    can_spend: bool = False

    def to_dict(self) -> dict:
        return {
            "status": self.status.value,
            "blockers": list(self.blockers),
            "evidence_count": self.evidence_count,
            "independent_source_count": self.independent_source_count,
            "owner_approval_required": self.owner_approval_required,
            "can_publish": self.can_publish,
            "can_spend": self.can_spend,
        }


class OpportunityValidator:
    """Conservative gate: evidence quality, not optimistic scoring."""

    REQUIRED_KINDS = {
        EvidenceKind.BUYER_SIGNAL,
        EvidenceKind.COMPETITOR,
        EvidenceKind.COST,
        EvidenceKind.LEGAL_OR_POLICY,
    }

    def evaluate(self, opportunity: Opportunity) -> ValidationReport:
        blockers = opportunity.validate()
        independent = [e for e in opportunity.evidence if e.independent_source]
        kinds = {e.kind for e in independent}
        if not any(e.kind is EvidenceKind.BUYER_SIGNAL for e in independent):
            blockers.append("missing independent buyer evidence; do not infer willingness to pay")
        missing = self.REQUIRED_KINDS - kinds
        if missing:
            blockers.append("missing evidence categories: " + ", ".join(sorted(k.value for k in missing)))
        if len({e.url for e in independent}) < 2:
            blockers.append("at least two distinct independent source URLs are required")
        if not opportunity.legal_risk_notes.strip():
            blockers.append("legal and marketplace-policy risks must be assessed")
        status = (ValidationStatus.INSUFFICIENT_EVIDENCE if not opportunity.evidence
                  else ValidationStatus.NEEDS_RESEARCH if blockers
                  else ValidationStatus.OWNER_REVIEW)
        return ValidationReport(
            status=status,
            blockers=tuple(blockers),
            evidence_count=len(opportunity.evidence),
            independent_source_count=len(independent),
        )
