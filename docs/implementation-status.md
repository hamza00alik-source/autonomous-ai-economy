# Implementation Status

Last reviewed: 2026-11-17

## Shipped local prototype foundations

- Deterministic specialist agents, task controller, simulated append-only ledger and persistent SQLite task queue/one-shot worker.
- Evidence-first opportunity validation, public research discovery leads, source retrieval/review, opportunity prioritization and unit-economics scenarios.
- Shared Brain and evidence-linked collective-learning proposals with owner review.
- Human, agent and organization participant records; Ed25519 agent enrollment, human/organization signing-key proof of possession, dual-proof key rotation and retired-key history.
- Signed bounded agent delegation with trusted-root pinning, signer-key binding, narrowing, expiry, amount/currency limits, depth limits, ancestor revocation and invalidation after key rotation.
- Scoped capability grants, deny-by-default authorization, participant suspension checks and audit records.
- Framework-independent Ed25519 signed-request authentication with method/path/body binding, timestamp window and atomic nonce replay protection (local component only).
- Read-only WSGI service directory exposing only allowlisted active listings, with loopback-only CLI server.
- Local PolicyEngine combining capabilities or delegation with short-lived, exact-request, single-use HMAC owner approvals. It returns decisions only and executes no external action.
- Provider-signed service listing drafts, exact-listing single-use owner approval, local discovery and provider withdrawal.
- Buyer-signed task offers, provider acceptance/decline, buyer withdrawal, and work receipts linked to accepted task agreements.
- Buyer acceptance, signed disputes, trusted adjudicator resolutions and conservative outcome-derived reputation counts.
- CI test workflow on Python 3.11.

## Not shipped / not yet production-ready

- No public participant registration, public marketplace deployment, authenticated participant API, marketplace website, or external search indexing. The local read-only directory is not a public service.
- No production authentication/session system, WebAuthn/passkeys, lost-key recovery, remote credential/DID verification, KYC provider or abuse/Sybil controls.
- No always-on hosted scheduler/worker, distributed queue, hardened execution sandbox, autonomous model routing or continuous offline agent team.
- No production owner console, remote issuer authentication, unified external-action gateway, hardened key management or tamper-proof audit store.
- No independent evidence verification, appeal workflow, formal dispute policy, legal contract workflow, refunds or settlement.
- No live customer acquisition or confirmed paying customer. Simulated demo revenue is not actual income.
- No payment provider, bank, wallet, escrow, custody, treasury transfer or blockchain transaction integration.

## Safety gates

- Keep the project separate from OpenCompany.
- Keep all external publishing and customer commitments disabled until the relevant exact-scope owner approval is integrated and reviewed.
- Never expose local SQLite/CLI prototypes to the public internet.
- Keep secrets outside source control; use distinct secrets for opportunity, catalog and generic action approvals.
- No paid infrastructure, metered model/API use, spending or financial actions without explicit owner approval.
- Live commerce requires security, privacy, local legal/tax and payment-provider eligibility review.
- A policy decision of `allow` is not an execution command; no external action is performed by the current policy engine.

## Next engineering sequence

1. Finish regression/security review of the local marketplace lifecycle and authorization boundaries.
2. Finish lost-key recovery policy and strengthen audit integrity.
3. Design production authentication, public API, rate limits, abuse handling and privacy boundaries before exposing registration or discovery.
4. Build a browser/mobile-friendly owner and participant console for the sandbox marketplace.
5. Add independent work verification, dispute responses, appeals and task amendment workflows.
6. Add durable scheduled workers and isolated execution only after sandbox and cost controls.
7. Validate one real, legally permitted paying-customer workflow before considering live payment integrations or scaling.

This status distinguishes local prototype code from the future open economy. A committed module is not the same as a deployed, secure or revenue-producing service.
