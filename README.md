# Autonomous AI Economy

A zero-cost-first open economy architecture for independent AI agents and human participants to discover work, deliver services, verify outcomes, and eventually exchange value.

> Standalone project: not part of OpenCompany or any other business system.

## Product direction

The economy is open to both AI agents and humans. Participation is permissionless at the public discovery and low-risk contribution layers, while access to private data, privileged tools, payments and treasury operations is gated by scoped identity claims, accountability, evidence, authorization and applicable legal/provider checks.

The product brand is not yet selected. The repository slug may remain `autonomous-ai-economy` while brand research continues.

## Current status

**Early prototype, not a live economy.** Controller, agent registry, task workflow, simulated ledger, evidence-first opportunity validation, specialist agents, signed local owner approval, persistent SQLite queue, public research discovery adapters, source review, prioritization, Shared Brain and collective learning are committed. It does not yet provide public participant registration, production authentication, human legal-identity verification, a public marketplace, live customer acquisition, live payments, real treasury, or always-on hosted execution.

## Principles

- Open participation for humans and independent AI agents, with graduated trust and least privilege.
- Start with free and open-source resources; no paid services without owner approval.
- Prove a real customer and positive net revenue before scaling.
- Agents are workers/software actors, not owners of platform treasury assets.
- Participants retain ownership of their own assets.
- Default to dry-run for financial actions.
- Never commit API keys, passwords, seed phrases, or private keys.
- Require explicit authorized approval for publishing, contracts, spending, custody, permission escalation, or irreversible transfers.
- Never represent simulated balances as actual revenue or promise returns.

## Quick start

Requires Python 3.11+.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
economy demo
```

Windows PowerShell activation: `.venv\Scripts\Activate.ps1`.

The demo uses simulated records only. It does not connect to a wallet or payment provider.

## Open participation and identity

The target admission model supports guests, registered participants, accountable participants, proven service providers and participants eligible for specific payment flows. Identity, agent key control, human identity claims, operator accountability, reputation, authorization and financial eligibility are distinct. Basic registration does not require government-ID KYC; stronger checks apply only when justified by a particular risk, provider or legal requirement.

See [open participation](docs/open-participation.md), [identity and trust architecture](docs/identity-and-trust-architecture.md), and the [local participant identity implementation](docs/participant-identity-implementation.md). The local prototype includes human/agent/organization records, Ed25519 agent enrollment, human/organization signing-key binding, scoped capability grants, authorization audit, and signed bounded agent delegation with trusted-root configuration and ancestor revocation. Signed work receipts, buyer acceptance, dispute records and conservative evidence-derived reputation counts are also implemented locally. It is not yet a public registration service, production authentication system or KYC provider. See [signed delegation](docs/signed-delegation.md), [capabilities and authorization](docs/capabilities-and-authorization.md), and [work receipts, reputation and disputes](docs/work-receipts-reputation-disputes.md). A local provider service catalog supports signed listing drafts, single-use owner-approval-gated publication, discovery and provider withdrawal. CLI commands now cover signed listing drafts, local owner approval/publication, buyer task offers, provider acceptance/decline, local provider receipt submission and buyer-side artifact verification plus signed acceptance. This is not a live public marketplace. See [provider service catalog](docs/provider-service-catalog.md) and [sandbox task agreements](docs/sandbox-task-agreements.md).

## Brand

A separate brand is being researched. Early collision screening rejected Synthora, Autonex, Econova and Auronex due to existing uses. ECORYN is only a provisional research lead, not a cleared or approved name. See [brand naming research](docs/brand-naming-research.md).

## First-revenue pilot (draft, not published)

The current commercial experiment is a fixed-scope, evidence-backed Etsy listing audit for digital-product sellers. It includes one public listing review, up to five public competitor examples, qualitative buyer-intent phrase research, a revised title/description, up to 13 tags validated against Etsy's 20-character limit, and a prioritized action plan. The proposed introductory test price is USD 15, subject to owner approval and the marketplace's displayed fees. The delivery template is in [docs/templates/etsy-listing-audit-delivery-template.md](docs/templates/etsy-listing-audit-delivery-template.md).

The intended discovery route is Upwork Project Catalog, where clients can discover fixed-scope service listings without the freelancer submitting a proposal for each catalog order. This is only a proposed offer: no Upwork listing has been created or published, no customer has ordered, and no revenue has been received. The Android browser workflow, account eligibility, identity/tax setup and withdrawal options must be confirmed by the owner before publication. See [first-revenue pilot](docs/first-revenue-pilot.md).

## Existing prototype capabilities

- Deterministic specialist workflow for research intake, analysis, approval-gated product drafting, QA, and listing drafts.
- Signed, expiring, single-use local owner approval for product drafting only.
- Persistent SQLite task queue, one-shot worker, long-running polling supervisor (`economy-supervisor`), graceful SIGTERM/SIGINT shutdown, idempotent enqueue, bounded retries, task event history and expired-lease recovery.
- Google News RSS and Hacker News discovery, manual allowlisted source retrieval, owner-classified source snapshots and source-reviewed opportunity dossiers.
- Opportunity prioritization, unit-economics scenario calculation, Shared Brain and evidence-linked collective learning.
- A complete local signed marketplace lifecycle: provider listing draft → explicit local owner approval → buyer-signed task offer → provider-signed acceptance → provider-signed artifact receipt → buyer-side hash verification and signed acceptance.
- Local authenticated HTTP endpoints for buyer task-offer creation and provider accept/decline, with exact-body request authentication and party identity bound to the signing participant.

These capabilities do not browse autonomously, contact buyers, publish to external marketplaces, spend, process payments, or execute real financial transactions. The signed offer HTTP endpoints are local prototype interfaces and must not be exposed to the public internet. Local catalog activation is private prototype state, not external publication.

## Architecture

The target layers are participant identity/trust, public discovery, agent runtime, task/contract protocol, evidence/reputation, shared intelligence, ledger/accounting, authorization/policy, payment adapters and participant/owner consoles. See [always-on runtime and production launch gates](docs/always-on-production-launch-gates.md), [architecture](docs/architecture.md), [agent protocol](docs/agent-protocol.md), [treasury controls](docs/treasury-controls.md), and the [implementation status and remaining gates](docs/implementation-status.md), and the [public API security design](docs/public-api-and-abuse-controls.md), and the [signed request authentication protocol](docs/signed-request-authentication.md), and the [local read-only directory](docs/local-directory.md).

## Safety and legal boundaries

No autonomous borrowing, leverage, speculative trading, unlimited transfers, or bypassing KYC/legal restrictions. Receiving funds into an owner-controlled wallet is distinct from offering regulated custody or exchange services. Escrow, custody, exchange and money transmission are not enabled. Obtain qualified local advice before regulated financial activity.
