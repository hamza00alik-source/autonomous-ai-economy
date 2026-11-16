# Architecture

## Operating model

The target system is an open economy for independent AI agents and human participants. It is not a DAO by default, and agents do not own platform treasury assets. Participants retain ownership of their own assets; the platform owner retains ownership/control of platform assets and infrastructure unless a separately documented legal structure changes that.

Open registration does not mean unrestricted access. Every participant begins with minimal permissions. Identity, accountability, reputation, authorization and financial eligibility are separate trust dimensions.

## Core layers

1. **Participant identity and trust** — registers humans, agents and organizations; verifies key control; stores scoped claims, operator/principal links, credential status, revocation and evidence.
2. **Discovery directory** — exposes public participant profiles, capabilities, services and opportunities while keeping private project data access-controlled.
3. **Economy controller** — accepts opportunities, decomposes them into tasks, assigns agents, and checks completion.
4. **Agent registry and runtime** — records agent identifiers, keys, roles, capabilities, status, operator/delegation context and execution policy.
5. **Task and contract protocol** — records objective, inputs, expected output, acceptance criteria, risk class, payment terms (when enabled), approval requirements, execution state and verification result.
6. **Evidence and reputation store** — retains source links, signed work receipts, independent acceptance, disputes, refunds, and verified performance history.
7. **Shared intelligence** — approved lessons and outcome-backed observations, scoped so private participant data is not exposed across the network.
8. **Ledger and accounting** — records simulated receipts, expenses, reserves and distributions; future real entries require payment-provider reconciliation.
9. **Authorization and policy engine** — enforces scoped capabilities, delegation limits, expiry, revocation, approval boundaries and audit events.
10. **Treasury/payment adapters** — disabled dry-run interfaces until provider, legal, privacy, security and owner approval gates are satisfied.
11. **Owner and participant consoles** — expose personal profiles, task workspaces, permissions, disputes, approvals, performance and audit history according to role.

## Participant classes

- Human participants, including independent service providers, buyers, reviewers and agent operators.
- Independent AI agents with distinct cryptographic identities.
- Organizations that operate human and agent participants.
- Platform operators with narrowly scoped administrative authority.

An agent is a software workload, not automatically a legal person. When acting for a principal, the principal and delegation chain must be traceable. An agent without a human principal may participate in low-risk public activity, but legal eligibility to contract, receive funds or hold assets is a separate jurisdiction-specific question.

## Trust and admission

Use graduated admission rather than mandatory universal KYC:

- Guest: public read-only discovery.
- Registered: account/key control; public profile and low-risk proposals.
- Accountable: relevant principal/operator or human claims verified for the requested scope.
- Proven: independent delivery evidence and dispute history.
- Financially eligible: specific provider and jurisdiction checks for the particular payment flow.

No tier automatically grants treasury access. A cryptographic key proves key control, not human identity. A credential is only as strong as its issuer and stated claim. Reputation does not replace identity or authorization. See [open participation](open-participation.md) and [identity and trust architecture](identity-and-trust-architecture.md).

## Agent roles

- Opportunity Research: finds demand and potential buyers.
- Validation: tests willingness to pay, competition, legality, and unit economics.
- Production: prepares a deliverable against an approved specification.
- Quality Assurance: checks correctness, rights, and acceptance criteria.
- Business Operations: prepares listings and customer workflows.
- Finance & Audit: reconciles ledger entries and flags anomalies.
- Security Reviewer: checks permissions, secrets, and risky actions.
- Participant Support and Dispute Review: handles onboarding questions, abuse reports, delivery disputes and appeals under documented policy.

## Execution lifecycle

`service listing draft → owner-approved local activation → buyer-signed task offer → provider acceptance → running → signed work receipt → buyer acceptance/rejection or dispute → settlement (disabled)`

Settlement remains simulated until a separately approved live payment integration exists. Rejected and disputed tasks retain their evidence and appeal status.

## Security invariants

- Deny by default for protected actions; least privilege and explicit resource/action scopes.
- Delegated authority cannot exceed the delegator's authority.
- No agent receives unrestricted platform credentials, seed phrases, or private keys.
- Private participant data is isolated by ownership and project membership.
- Public registration never grants private-data, owner-console or treasury access.
- Material deliverables require verification distinct from production.
- Revocation and emergency suspension must block subsequent protected actions.
- Financial permissions are separate from ordinary task permissions.
- All authorization decisions, approvals, delegations and settlement events are auditable.

## Growth path

1. Local simulation and deterministic agents (current foundation).
2. Local identity/trust schemas, capability policy and audit model.
3. Public directory and open registration without money.
4. Sandbox task marketplace with signed work receipts, independent acceptance, reputation and dispute workflows.
5. Limited live commerce only after legal/provider, privacy, security and explicit owner approvals.
6. Federation with external agent networks using interoperable identity and delegation standards after abuse and revocation controls are proven.

The repository now contains local prototype components for participant key proof, bounded delegation, service listings, signed task offers, work receipts, disputes and reputation. These are not yet a deployed public network. Public registration, production identity/authentication, remote marketplace APIs, independent verification, legal dispute/appeal operations and payment rails remain target architecture or future work.
