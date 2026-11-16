# Specialist agent workflow

## Current implementation

These are deterministic local processors. They operate on data passed into them and do not connect to the internet, external AI models, payment systems, or marketplaces.

1. **MarketResearchAgent** organizes supplied evidence into a research brief and reports missing evidence categories. It explicitly marks that it did not perform external research.
2. **OpportunityAnalystAgent** evaluates an opportunity using the evidence validator. Missing evidence blocks progression.
3. **ProductBuilderAgent** creates a structured product draft only when the caller supplies explicit owner approval and the opportunity reaches the validator's owner-review status.
4. **QualityAssuranceAgent** checks required product fields, core contents, draft status, and disclaimers.
5. **BusinessOperationsAgent** prepares an unpublished listing draft only after QA passes. The result explicitly remains unpublished and does not contact customers.

## Approval boundaries

- Product drafting requires explicit owner approval and a completed evidence checklist.
- QA failure blocks listing-draft preparation.
- Listing drafts are never published by this workflow.
- No agent spends money, creates binding offers, signs contracts, contacts customers, or moves funds.
- Owner review is still required for factual accuracy, originality, IP rights, local legal requirements, marketplace eligibility, pricing, fees, and taxes.

## Example

```python
from economy.specialist_agents import (
    ProductBuilderAgent, QualityAssuranceAgent, BusinessOperationsAgent,
)

# opportunity must contain validated evidence and be owner-approved first
product = ProductBuilderAgent().create_draft(opportunity, owner_approved=True)
qa = QualityAssuranceAgent().review(product)
if qa.passed:
    listing_draft = BusinessOperationsAgent().prepare_listing(product, qa)
    assert listing_draft.published is False
```

## Not yet implemented

Live web research, source authenticity checks, LLM/model routing, persistent memory, autonomous scheduling, a background worker, marketplace connectors, payment adapters, and real customer fulfillment are future work. The present agents are useful deterministic workflow components, not autonomous online businesses.