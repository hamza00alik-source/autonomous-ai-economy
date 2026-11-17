# Always-on runtime and production launch gates

Status: implementation baseline and launch-control specification. This document does not mean a hosted service is deployed or approved.

## What "always-on" means

The repository now has a long-running single-host supervisor entry point, `economy-supervisor`. It repeatedly invokes the existing fixed built-in worker, waits between idle cycles, records basic process counters in logs, and handles SIGTERM/SIGINT by stopping after the current worker cycle. The durable SQLite queue remains the recovery source after process restart.

This is a single-process, single-host baseline—not high availability, a distributed queue, multi-region service, or proof of continuous uptime. The built-in worker still requires Linux Bubblewrap and its configured isolation support. Do not expose the local WSGI directory or SQLite database directly to the internet.

## Separate infrastructure target

Keep this economy on its own account/project, network, database, object storage, secrets scope, monitoring, billing account and deployment pipeline. Do not share OpenCompany infrastructure, credentials, data, domains, or operational dependencies.

Production target (not yet provisioned):

- Public edge: managed TLS, DDoS protection, WAF, request-size/rate limits and bot/abuse controls.
- Application: stateless public API and web frontend; private worker/scheduler pool; separate admin/owner control plane.
- Data: managed PostgreSQL with migrations, point-in-time recovery and tested restore; private object storage for deliverables; append-only external audit export.
- Queue: durable broker with visibility timeout, idempotency keys, bounded retries, dead-letter handling and operational replay.
- Secrets: managed secret store/KMS; short-lived workload identity; rotation and emergency revocation; no secrets in GitHub, logs, images or client apps.
- Isolation: per-job sandbox/VM or hardened container, no host socket, no ambient credentials, egress allowlist, resource quotas and independent security validation.
- Observability: metrics, structured redacted logs, traces, uptime checks, alert routing, incident runbooks and status page.
- Recovery: encrypted backups, tested restore, RPO/RTO targets, region/provider outage plan and documented owner break-glass procedure.

The initial supervisor is not a substitute for these services. Do not deploy it as a public-facing application.

## Customer-facing launch sequence

1. Public read-only service discovery with abuse protection and privacy review.
2. Account creation, verified email, passkeys/session security, recovery and rate limits.
3. Buyer/provider profiles, reporting, blocklists, moderation and appeals.
4. Signed offers, clear service terms, cancellation/refund policy, evidence retention and dispute workflow.
5. Limited invite-only pilot with manual customer support and no automated money movement.
6. Payment-provider hosted checkout and signed webhooks only after provider approval, legal review, security review and explicit owner authorization.
7. Reconciliation, refunds, chargebacks, tax/accounting exports and settlement controls; begin with manual payout approval.
8. Expand geography and automation only after real operational evidence.

Do not claim customer traction until a real customer has contracted and paid. Do not count simulated ledger entries, test-mode payments or unsigned webhook payloads as revenue.

## Payment design: mandatory boundaries

The platform must not hold customer funds, operate escrow, issue stored value, or custody crypto by default. Prefer a licensed payment provider's hosted checkout and provider-managed settlement to the verified merchant account. A provider's availability, supported country, merchant eligibility, currencies, fees, settlement timing, refunds, chargebacks and marketplace/platform rules must be confirmed directly before selection.

Required integration properties:

- Create payment intents server-side with immutable order IDs, amount, currency, buyer, provider and accepted agreement fingerprint.
- Never trust client-supplied payment status, amount, currency or redirect success.
- Verify webhook signatures against raw request bytes; enforce timestamp tolerance, event-ID uniqueness and idempotent processing.
- Store provider event IDs and immutable state transitions; reconcile against provider reports/API.
- Separate authorization, capture, refund and payout states; no agent may alter settlement destination.
- Manual owner approval for refunds, payouts, reserves, bank-detail changes and any irreversible financial action in the first release.
- Never store card PAN/CVV; use provider-hosted payment components and tokenization.
- Use double-entry accounting for platform fees and liabilities; provider settlement reports are the external source of truth.
- Payment secrets are runtime-only in a secret manager, rotated, least-privilege and never available to worker agents.

No payment provider is currently connected. No live payment endpoint, webhook, payout, wallet or treasury transfer is enabled.

## Security approval gates

Before internet exposure, obtain an independent review covering threat model, authentication/session handling, authorization, tenant isolation, SSRF, injection, file upload and malware, sandbox escape, dependency/supply-chain risk, secrets, webhook replay, rate limits, privacy, logging, backups and incident response. Resolve critical/high findings and document accepted residual risk. Run SAST, dependency and secret scanning, DAST against staging, penetration testing and restore/incident exercises. CI passing is not a security audit.

Operational controls: MFA/passkeys for owners, two-person review for production changes, protected main branch, signed releases, pinned dependencies/actions, least-privilege CI, environment separation, immutable backups, audit export outside the primary database, alerting and tested kill switch.

## Legal, regulatory and tax approval gates

Obtain qualified advice for the operator's actual legal entity and each target market before onboarding buyers/providers or processing money. Review, at minimum:

- Whether the business is a marketplace, agent, software provider, payment facilitator, money transmitter, escrow/custody provider or another regulated activity.
- Pakistan business/entity, tax, invoicing, foreign-exchange, banking and payment-provider requirements.
- Consumer protection, digital services, e-commerce, unfair terms, refunds, chargebacks and complaint handling.
- Privacy/data protection, cross-border transfers, retention/deletion, cookies and breach notification.
- Sanctions screening, prohibited services, fraud/AML obligations and any provider-imposed KYC/KYB.
- Contractor/worker classification, agency and authority to bind principals, IP ownership/licensing, warranties and liability.
- AI disclosure, agent accountability, prohibited-use policy and recordkeeping.
- Terms of service, privacy notice, provider agreement, buyer agreement, dispute policy and acceptable-use policy.

Do not assume that calling the platform "decentralized", using AI agents, or routing money through a third party removes legal obligations. A lawyer's review and the payment provider's written merchant approval are external deliverables; code cannot grant them.

## Launch decision record

Production launch remains blocked until every applicable item has an owner, evidence link, reviewer and approval date:

- [ ] Separate infrastructure account/project and budget approved.
- [ ] Legal entity, operating model and target jurisdictions approved by qualified counsel.
- [ ] Payment provider confirms merchant and marketplace model eligibility in writing.
- [ ] Privacy notices, terms, customer/provider agreements and dispute/refund policies reviewed.
- [ ] Independent security assessment completed; critical/high findings closed or formally accepted.
- [ ] Production secrets/KMS, database, backups, monitoring and incident response verified.
- [ ] Authentication, abuse controls, moderation and account recovery tested.
- [ ] Payment webhook, idempotency, reconciliation, refunds and manual payout controls tested in provider sandbox.
- [ ] Staging end-to-end test and restore/incident drills passed.
- [ ] Owner explicitly approves the exact production release, provider, geography, limits and financial permissions.

## Current truthful status

Implemented locally: a long-running polling supervisor over the existing durable single-host queue. Not implemented or approved: public production hosting, public buyer accounts, production authentication, live payment processing, provider merchant approval, legal opinions, independent security audit, customer acquisition, or real revenue.
