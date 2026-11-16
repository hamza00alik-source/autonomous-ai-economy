# Architecture

## Operating model

The first deployment is a private, owner-controlled economy. It is not a DAO and agents do not own treasury assets.

## Components

1. **Economy controller** — accepts opportunities, decomposes them into tasks, assigns agents, and checks completion.
2. **Agent registry** — records each agent's identifier, role, capabilities, status, and permitted actions.
3. **Task protocol** — records objective, inputs, expected output, risk class, owner-approval requirement, execution state, and verification result.
4. **Evidence store** — retains source links, work artifacts, test results, and decision records.
5. **Ledger** — append-only records of simulated receipts, expenses, reserves, and distributions.
6. **Treasury adapter** — initially a dry-run interface. Real payment rails are a later, separately gated phase.
7. **Owner console** — exposes approvals, limits, performance, and audit history.

## Agent roles

- Opportunity Research: finds demand and potential buyers.
- Validation: tests willingness to pay, competition, legality, and unit economics.
- Production: prepares a deliverable against an approved specification.
- Quality Assurance: checks correctness, rights, and acceptance criteria.
- Business Operations: prepares listings and customer workflows.
- Finance & Audit: reconciles ledger entries and flags anomalies.
- Security Reviewer: checks permissions, secrets, and risky actions.

## Execution lifecycle

`proposed → approved → assigned → running → submitted → verified → completed`

A failed or rejected task is marked accordingly and retains its evidence. High-risk tasks pause for owner approval.

## Growth path

Private single-owner operation first. Only after stable operations and legal review should external agents be admitted through identity, capability, reputation, service-contract, dispute, and settlement controls.
