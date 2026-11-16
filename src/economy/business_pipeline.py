"""End-to-end deterministic opportunity-to-listing-draft orchestration."""
from __future__ import annotations

from dataclasses import dataclass

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

    def __init__(self) -> None:
        self.researcher = MarketResearchAgent()
        self.analyst = OpportunityAnalystAgent()
        self.builder = ProductBuilderAgent()
        self.qa_agent = QualityAssuranceAgent()
        self.operations = BusinessOperationsAgent()

    def run(self, opportunity: Opportunity, *, owner_approved: bool = False) -> PipelineResult:
        research = self.researcher.prepare_brief(
            f"Assess opportunity: {opportunity.title}", opportunity.evidence
        )
        analysis = self.analyst.analyze(opportunity)
        if analysis.report.status is not ValidationStatus.OWNER_REVIEW:
            return PipelineResult(research, analysis, None, None, None,
                                  "blocked_research", analysis.report.blockers)
        if not owner_approved:
            return PipelineResult(research, analysis, None, None, None,
                                  "awaiting_owner_approval",
                                  ("Owner approval is required before product drafting.",))
        product = self.builder.create_draft(opportunity, owner_approved=True)
        qa = self.qa_agent.review(product)
        if not qa.passed:
            return PipelineResult(research, analysis, product, qa, None,
                                  "blocked_quality_assurance", qa.issues)
        listing = self.operations.prepare_listing(product, qa)
        return PipelineResult(research, analysis, product, qa, listing,
                              "listing_draft_ready", ())