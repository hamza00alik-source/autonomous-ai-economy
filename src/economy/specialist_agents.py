"""Specialist agents for a private, approval-gated digital business workflow.

All agents are deterministic local processors. They do not browse the web, call
paid model APIs, publish listings, spend funds, or contact customers.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .opportunities import (
    Evidence, Opportunity, OpportunityValidator, ValidationReport, ValidationStatus,
)


@dataclass(frozen=True)
class ResearchBrief:
    question: str
    evidence: tuple[Evidence, ...]
    evidence_gaps: tuple[str, ...]
    claims: tuple[str, ...]
    external_research_performed: bool = False


class MarketResearchAgent:
    """Organizes supplied sources; never invents findings or claims to browse."""

    agent_id = "market-research"
    role = "market research"

    def prepare_brief(self, question: str, evidence: Iterable[Evidence]) -> ResearchBrief:
        question = " ".join(question.split())
        if not question:
            raise ValueError("research question is required")
        rows = tuple(evidence)
        claims = tuple(
            f"{item.kind.value}: {item.finding.strip()} (source: {item.source_name}; {item.url})"
            for item in rows if item.finding.strip()
        )
        present = {item.kind for item in rows if item.independent_source}
        gaps = []
        for kind in (
            "buyer_signal", "competitor", "cost", "legal_or_policy",
        ):
            if kind not in {value.value for value in present}:
                gaps.append(f"Missing independent {kind.replace('_', ' ')} evidence")
        return ResearchBrief(question, rows, tuple(gaps), claims)


@dataclass(frozen=True)
class AnalysisResult:
    opportunity: Opportunity
    report: ValidationReport
    recommendation: str


class OpportunityAnalystAgent:
    agent_id = "opportunity-analyst"
    role = "opportunity analysis"

    def __init__(self, validator: OpportunityValidator | None = None) -> None:
        self.validator = validator or OpportunityValidator()

    def analyze(self, opportunity: Opportunity) -> AnalysisResult:
        report = self.validator.evaluate(opportunity)
        recommendation = (
            "Submit for owner review; this is not approval to launch."
            if report.status is ValidationStatus.OWNER_REVIEW
            else "Do not proceed to product creation; close the evidence gaps first."
        )
        return AnalysisResult(opportunity, report, recommendation)


@dataclass(frozen=True)
class ProductDraft:
    title: str
    buyer_segment: str
    problem: str
    solution: str
    format: str
    contents: tuple[str, ...]
    disclaimers: tuple[str, ...]
    status: str = "draft"


class ProductBuilderAgent:
    agent_id = "product-builder"
    role = "product creation"

    def create_draft(self, opportunity: Opportunity, *, owner_approved: bool) -> ProductDraft:
        if not owner_approved:
            raise PermissionError("owner approval is required before product drafting")
        if opportunity.validate():
            raise ValueError("opportunity fields must be valid before drafting")
        contents = (
            "Quick-start instructions",
            "Core worksheet or template",
            "Worked example clearly labelled as illustrative",
            "Checklist for user completion",
        )
        disclaimers = (
            "Draft content only; verify accuracy and originality before sale.",
            "No affiliation with third-party games, brands, or platforms is implied.",
        )
        return ProductDraft(
            title=opportunity.title,
            buyer_segment=opportunity.buyer_segment,
            problem=opportunity.problem,
            solution=opportunity.proposed_solution,
            format=opportunity.delivery_format,
            contents=contents,
            disclaimers=disclaimers,
        )


@dataclass(frozen=True)
class QAResult:
    passed: bool
    checks: tuple[str, ...]
    issues: tuple[str, ...]


class QualityAssuranceAgent:
    agent_id = "quality-assurance"
    role = "quality assurance"

    REQUIRED_CONTENT = {
        "Quick-start instructions",
        "Core worksheet or template",
        "Worked example clearly labelled as illustrative",
        "Checklist for user completion",
    }

    def review(self, draft: ProductDraft) -> QAResult:
        issues = []
        if not draft.title.strip():
            issues.append("product title is missing")
        if not draft.buyer_segment.strip():
            issues.append("buyer segment is missing")
        if not draft.solution.strip():
            issues.append("solution description is missing")
        if not draft.format.strip():
            issues.append("delivery format is missing")
        missing = self.REQUIRED_CONTENT - set(draft.contents)
        if missing:
            issues.append("missing required content: " + ", ".join(sorted(missing)))
        if draft.status != "draft":
            issues.append("product must remain in draft status")
        if not draft.disclaimers:
            issues.append("review disclaimers are required")
        checks = (
            "Required product fields checked",
            "Core deliverable structure checked",
            "Draft-only status checked",
            "Disclaimers checked",
        )
        return QAResult(not issues, checks, tuple(issues))


@dataclass(frozen=True)
class ListingDraft:
    title: str
    description: str
    format: str
    status: str = "draft"
    published: bool = False
    customer_contacted: bool = False


class BusinessOperationsAgent:
    agent_id = "business-operations"
    role = "business operations"

    def prepare_listing(self, draft: ProductDraft, qa: QAResult) -> ListingDraft:
        if not qa.passed:
            raise ValueError("quality assurance must pass before listing preparation")
        description = (
            f"For: {draft.buyer_segment}.\n\n"
            f"Problem addressed: {draft.problem}.\n\n"
            f"What it provides: {draft.solution}.\n\n"
            f"Included: " + "; ".join(draft.contents) + ".\n\n"
            "Review the final file, marketplace rules, pricing, taxes, and fees "
            "before publishing. This is a draft, not a live offer."
        )
        return ListingDraft(draft.title, description, draft.format)
