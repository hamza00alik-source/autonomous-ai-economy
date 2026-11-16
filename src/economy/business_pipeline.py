"""End-to-end deterministic opportunity-to-listing-draft orchestration."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .approvals import OwnerApprovalStore
from .opportunities import Opportunity, ValidationStatus
from .specialist_agents import (
    AnalysisResult, BusinessOperationsAgent, ListingDraft, MarketResearchAgent,
    OpportunityAnalystAgent, ProductBuilderAgent, ProductDraft,
    QualityAssuranceAgent, QAResult, ResearchBrief,
)


@dataclass(frozen=True)
class PipelineResult:
    research: ResearchBrief
    analysis: AnalysisResult
    product: ProductDraft | None
    qa: QAResult | None
    listing: ListingDraft | None
    status: str
    blockers: tuple[str, ...]


class OpportunityToListingPipeline:
    """Runs local stages; publishing, spending, and customer contact are absent."""

    def __init__(self, approval_store: OwnerApprovalStore | None = None) -> None:
        self.researcher = MarketResearchAgent()
        self.analyst = OpportunityAnalystAgent()
        self.builder = ProductBuilderAgent()
        self.qa_agent = QualityAssuranceAgent()
        self.operations = BusinessOperationsAgent()
        self.approval_store = approval_store or OwnerApprovalStore()

    def run(
        self,
        opportunity: Opportunity,
        *,
        approval_token: str | None = None,
        approval_secret: str | bytes | None = None,
    ) -> PipelineResult:
        research = self.researcher.prepare_brief(
            f"Assess opportunity: {opportunity.title}", opportunity.evidence
        )
        analysis = self.analyst.analyze(opportunity)
        if analysis.report.status is not ValidationStatus.OWNER_REVIEW:
            return PipelineResult(research, analysis, None, None, None,
                                  "blocked_research", analysis.report.blockers)
        if not approval_token or approval_secret is None:
            return PipelineResult(research, analysis, None, None, None,
                                  "awaiting_owner_approval",
                                  ("A signed, unexpired, single-use owner approval token is required.",))
        approved, reason = self.approval_store.consume(
            approval_token, opportunity, approval_secret
        )
        if not approved:
            return PipelineResult(research, analysis, None, None, None,
                                  "awaiting_owner_approval", (reason,))
        product = self.builder.create_draft(opportunity, owner_approved=True)
        qa = self.qa_agent.review(product)
        if not qa.passed:
            return PipelineResult(research, analysis, product, qa, None,
                                  "blocked_quality_assurance", qa.issues)
        listing = self.operations.prepare_listing(product, qa)
        return PipelineResult(research, analysis, product, qa, listing,
                              "listing_draft_ready", ())
