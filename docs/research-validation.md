# Opportunity research and validation

## Purpose

Prevent the economy from treating ideas, search snippets, or visible listings as proven demand. This is an intake and quality gate, not a live research engine.

## Required evidence

For a candidate to reach owner review, the validator requires:

- An independent buyer signal (for example, a verifiable transaction indicator, buyer request, or credible paid-demand dataset).
- Competitor evidence.
- Cost evidence, including relevant platform or delivery fees.
- Legal or marketplace-policy evidence.
- At least two distinct independent source URLs.
- A written legal/policy risk assessment.

Each evidence record stores a source name, URL, observation date, evidence category, and a concise finding. Evidence URLs must be absolute HTTP(S) URLs. Source independence is explicitly recorded and must be checked by the researcher; the current deterministic validator cannot prove that two publishers are editorially independent.

## Status meanings

- `insufficient_evidence`: no evidence has been supplied.
- `needs_research`: evidence or required fields are missing or invalid.
- `owner_review`: the minimum evidence checklist is complete. This is not a business approval or a guarantee of demand.

The report always sets `owner_approval_required=true`, `can_publish=false`, and `can_spend=false`.

## Important limitations

- No live search, browsing, scraping, or external source verification is implemented yet.
- A listing or advertised sales figure is not automatically proof of completed transactions.
- The system does not estimate conversion rates, revenue, or profit from unsupported assumptions.
- Human review is required for source credibility, legal interpretation, intellectual-property checks, and marketplace eligibility.
- Do not use customer data without a lawful basis and appropriate privacy safeguards.

## Example integration

Construct an `Opportunity` with an evidence tuple and call `OpportunityWorkflow().assess(opportunity)`. Review the returned blockers and status. Do not bypass the owner approval boundary in downstream publishing or payment code.
