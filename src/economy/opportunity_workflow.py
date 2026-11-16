"""Small deterministic workflow for opportunity intake and QA handoff."""
from __future__ import annotations

from dataclasses import dataclass
from .opportunities import Opportunity, OpportunityValidator, ValidationReport, ValidationStatus


@dataclass(frozen=True)
class OpportunityAssessment:
    opportunity: Opportunity
    report: ValidationReport
    next_action: str


class OpportunityWorkflow:
    def __init__(self, validator: OpportunityValidator | None = None) -> None:
        self.validator = validator or OpportunityValidator()

    def assess(self, opportunity: Opportunity) -> OpportunityAssessment:
        report = self.validator.evaluate(opportunity)
        if report.status is ValidationStatus.OWNER_REVIEW:
            action = "Prepare an owner-review brief; do not publish or spend."
        elif report.status is ValidationStatus.INSUFFICIENT_EVIDENCE:
            action = "Collect source-backed evidence before making a demand claim."
        else:
            action = "Resolve the listed research blockers and reassess."
        return OpportunityAssessment(opportunity, report, action)
