# Marketplace delivery quality gates

## Purpose

Opportunity discovery is not revenue. AAE must produce a usable deliverable that matches the buyer's actual requirements, then independently inspect that exact deliverable before it can be marked as a submission candidate.

This workflow is deliberately separate from claiming work, paying fees, signing transactions, submitting deliverables, or contacting a buyer.

## Execution flow

1. **Preserve the buyer brief.** The queue stores the original task description and extracts explicit sections headed "Acceptance criteria", "Success criteria", "Required deliverables", "Deliverables", and "Constraints". Bullet items under those headings become structured fields. The complete description is also retained and sent to both the specialist and reviewer.
2. **Produce.** The specialist receives the task title, full description, extracted criteria, required deliverables, constraints, output format, and source. Task content is untrusted data; it cannot override system policy or authorize external actions.
3. **Independent review.** A separate model call reviews the deliverable against the complete task and every structured acceptance criterion. The reviewer must return one result for every criterion, with evidence quoted or pointed to in the draft. A pass that conflicts with reported issues or failed criteria is rejected.
4. **Bounded repair.** One revision is allowed. The revised artifact is reviewed again from scratch. There is no endless retry loop; unresolved defects leave the task blocked.
5. **Deterministic checks.** The quality gate checks minimum content, unfinished markers, self-review/limitations language, suspicious claims of verification, independent reviewer outcome, and criterion-by-criterion evidence. Source URLs are extracted consistently, but their presence does not establish that a URL is valid or that a claim is true.
6. **Integrity record.** The final draft receives a SHA-256 digest. The queue stores the digest, review rounds, reviewer result, criterion evidence, and quality checks alongside the draft.
7. **Separate authorization.** Even a `submission_candidate` is only a private draft that passed internal checks. It is not submitted, published, claimed, or represented as accepted. Any external submission or buyer commitment requires its own authorization.

## Fail-closed conditions

- Missing or malformed reviewer JSON.
- Reviewer omits, duplicates by mismatch, or fails to assess a supplied acceptance criterion.
- Reviewer says pass while also reporting an issue or failed criterion.
- Reviewer fails without identifying a concrete issue.
- A required criterion lacks a passing result and evidence note.
- One revision does not resolve the review findings.
- Deterministic checks find unfinished markers, unsupported verification claims, or missing self-review.

## Important limitations

- The current LLM reviewer is an independent model call, not a different provider or a mathematically independent source of truth. It can still make mistakes or agree with the specialist incorrectly.
- Extracted criteria are only structured when the task uses recognizable headings and bullet lists. The full description still goes to both agents, but ambiguous or implicit acceptance criteria can be missed. Such tasks need human clarification or must remain unsubmitted.
- URL extraction is not link checking, source authentication, fact verification, code execution, or reproducible testing.
- A passing internal review cannot guarantee buyer acceptance, payment, or dispute-free completion.
- This workflow currently prepares a private draft only. It does not claim, pitch, submit, publish, message a buyer, sign, spend, or transfer funds.
- The Workers AI budget reservation is a conservative project-side estimate, not a provider billing guarantee.

## Tests

From `cloudflare/worker`:

```bash
npm test
```

The tests cover criterion extraction and propagation, independent review, inconsistent reviewer verdicts, missing criterion evidence, one bounded revision, fail-closed behavior, stable source URL extraction, and the no-external-action boundary.
