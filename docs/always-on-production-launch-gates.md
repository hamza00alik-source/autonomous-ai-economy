# Always-on runtime and production launch gates

Status: implementation baseline and launch-control specification. This document does not mean a hosted service is deployed or approved.

## What "always-on" means

The repository now has a long-running single-host supervisor entry point, `economy-supervisor`. It repeatedly invokes the existing fixed built-in worker, waits between idle cycles, records basic process counters in logs, and handles SIGTERM/SIGINT by stopping after the current worker cycle. The durable SQLite queue remains the recovery source after process restart.

This is a single-process, single-host baseline—not high availability, a distributed queue, multi-region service, or proof of continuous uptime. The built-in worker still requires Linux Bubblewrap and its configured isolation support. Do not expose the local WSGI directory or SQLite database directly to the internet.

## AI model worker lane

The local supervisor now has two separate execution lanes:

- Fixed built-in handlers run inside the existing no-network Bubblewrap sandbox.
- The optional `ai-product-copy-agent` claims only its own exact task ID and calls the allowlisted Cloudflare Workers AI model from a separate process. It has no shell, browser, arbitrary tool, payment, publishing, or customer-contact capability.

Queue a product-copy task with `economy-ai queue-copy --facts-file products/moba-objective-props/product-facts.json`. The supervisor processes it only when valid Cloudflare credentials are present. With no credentials, the task remains queued. Model failures are single-attempt by default and the estimated daily usage budget is persisted locally.

This is a first bounded model-backed agent lane, not a general multi-agent runtime. It is still a local single-host process; it is not hosted, always-on in production, or connected to a public customer storefront. The API token must be supplied through the host's secret environment, never committed to source control.

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


## Payment-provider discovery for a Pakistan-based operator

Research checked 17 November 2026; this is a shortlist for direct eligibility confirmation, not an approval or final selection.

- **Stripe:** Pakistan is not present in Stripe's current supported-country list. Do not plan a Pakistan-registered merchant integration around Stripe unless the actual operating legal entity and banking footprint qualify in a supported jurisdiction under Stripe's published requirements. Do not use nominee accounts, borrowed identities or fictitious overseas addresses. Sources: https://stripe.com/global and https://support.stripe.com/questions/requirements-to-open-a-stripe-account-in-another-country
- **Payoneer:** Payoneer publicly documents client payment requests, marketplace payouts and Payoneer Checkout. Its own Pakistan guide describes Checkout for businesses receiving international payments, but availability is eligibility- and product-specific. The operator must obtain written confirmation that its exact entity, business model, platform/marketplace use, countries, currencies and split/payout flow are accepted. A personal Payoneer account or ability to withdraw funds does not automatically authorize operating a multi-vendor marketplace or collecting on behalf of third parties. Sources: https://www.payoneer.com/resources/business/guide-to-payment-gateways-in-pakistan/ and https://www.payoneer.com/
- **Pakistan domestic gateway route:** SBP's published authorized PSO/PSP list identifies commercial e-commerce gateway operators including NIFT, Avanza Premier Payment Services and Safepay (Pvt.) Ltd. This is a starting point for a merchant inquiry, not an endorsement or proof that any provider accepts this platform's business model, international cards, split settlements or payouts. Ask each provider for written confirmation. Source: https://www.sbp.org.pk/PS/PDF/List-PSOs-PSPs.pdf
- **Raast P2M:** SBP's rules describe merchant acceptance modes and say Raast Merchant Service Providers onboard merchants, aggregators and marketplaces after due diligence. It may be relevant to Pakistan-based customer payments, but it is not itself a global card acquiring or marketplace payout solution. Source: https://www.sbp.org.pk/circulars/pspod-circular-no-04-of-2023

Recommended decision: do not hard-code a gateway yet. First choose the legal operating entity and commercial model (platform principal vs independent provider marketplace vs software-only referral directory), then request written underwriting from Payoneer and at least two SBP-listed e-commerce gateway providers. Prefer a provider-managed merchant checkout and provider-managed settlement directly to each eligible seller if the provider supports that exact arrangement. If only one platform merchant account is approved, do not collect or redistribute third-party funds until counsel and the provider confirm that model is permitted.
