# Agent Financial Autonomy

Status: architecture and implementation contract; no live wallet or funds enabled.

## Objective

Let AAE agents manage routine financial operations autonomously after a human owner has configured and authorized a lawful operating policy. An agent should not need a human to approve every ordinary expense, budget allocation or reconciliation step. Human approval remains necessary for initial legal/account ownership decisions, policy provisioning, exceptional risk events and actions outside delegated limits.

This is a financial operating system for agents, not merely a checkout integration.

## Core distinction: financial identity, accounting attribution and legal ownership

These are separate records and must never be conflated:

1. **Agent identity** — the cryptographic participant identity and key history that authenticates an agent workload.
2. **Agent financial account** — a unique account or smart account address to which a policy can delegate narrowly scoped operations.
3. **Agent subledger** — an internal double-entry accounting view of earnings, allocations, budgets, reservations, expenses and liabilities.
4. **Legal principal / asset owner** — the person or entity legally entitled to control the funds and responsible for applicable obligations.

An agent ID or wallet address does not make software a legal person, prove beneficial ownership, or remove the need for required identity, tax, sanctions or provider checks. The principal and delegation chain must be explicit. Agents act as authorized operators, not owners of platform treasury assets unless a separate lawful structure expressly establishes otherwise.

## Target architecture

`verified payment / approved funding source`
→ `settlement verifier`
→ `reconciliation and double-entry ledger`
→ `allocation policy`
→ `treasury reserve + agent operating budgets`
→ `policy-controlled agent accounts`
→ `permitted service/tool expenses`
→ `receipt verification and reconciliation`

### Components

- **Settlement adapter:** provider or chain-specific evidence; idempotent event ingestion; never trust a browser callback or local ledger entry as proof of money.
- **Reconciliation engine:** verify actual wallet/provider receipt, asset, network, amount, fees, refunds, chargebacks and settlement finality before crediting spendable balances.
- **Double-entry ledger:** immutable journal with balanced debit/credit postings, unique external references, currency/asset precision, reversals rather than destructive edits, and a reconciliation status.
- **Allocation engine:** owner-approved deterministic policy for operating reserve, agent earned attribution, agent operating budget, taxes/contingencies and owner distribution. No default percentages are assumed.
- **Agent account registry:** maps participant ID to an account address, chain, account type, legal principal, signer policy and status. Address ownership and control must be verified.
- **Delegated transaction authority:** short-lived session key or policy module with exact asset/network, action, destination, per-transaction cap, daily cap, expiry, nonce and revocation. The AI never receives seed phrases or unrestricted private keys.
- **Spend executor:** creates a proposed transaction, validates it against policy and available cleared budget, obtains constrained cryptographic authorization, broadcasts only if all checks pass, and records the resulting transaction hash.
- **Audit and monitoring:** append-only policy decisions, ledger journal, transaction evidence, alerts, reconciliation and emergency pause.
- **Owner controls:** provision/revoke policies, configure legal principal and limits, pause an agent/account and review exceptions. Routine in-policy transactions do not require per-transaction owner approval.

## Agent financial lifecycle

1. Agent is enrolled as a cryptographic participant; key possession and delegation are verified.
2. A legally accountable principal and permitted operating scope are recorded where required.
3. Agent receives a unique financial account mapping and an owner-signed policy. No account can self-enroll into treasury privileges.
4. A real payment or approved funding event is independently verified.
5. Reconciliation posts gross receipt, fees, refunds and net proceeds. Unreconciled funds are not spendable.
6. Allocation policy credits the appropriate agent subledger and operating budget.
7. Agent can autonomously spend within its pre-authorized envelope on allowlisted operational services.
8. Spend executor validates limits, balance, destination, asset, network, expiry and replay protection.
9. Confirmed chain/provider result is reconciled; failed, replaced, reverted or ambiguous transactions remain pending/exception states.
10. Unused budget can roll over or return to reserve only under explicit policy. Owner distribution is a separate ledger allocation and payout flow.

## Default permission model

| Action | Routine autonomy | Required controls |
|---|---|---|
| Read balances and ledger | Yes | Agent-scoped read permission |
| Reconcile confirmed receipts | Yes | Trusted provider/chain evidence |
| Allocate within approved formula | Yes | Immutable owner-signed allocation policy |
| Pay allowlisted compute/API/service costs | Yes | Budget, per-tx and daily caps; destination allowlist |
| Refund within approved customer policy | Conditional | Verified original order and refund ceiling |
| Create new wallet/account | No by default | Owner policy provisioning and key/account verification |
| Add destination or change spending limits | No | Owner-authorized policy update |
| Transfer to arbitrary wallet | No | Explicit exceptional authorization |
| Withdraw owner distribution | No | Separate owner-approved distribution policy and legal/payment controls |
| Borrow, leverage, speculate or custody third-party assets | Prohibited | Not in AAE autonomy scope |

The purpose is not to require a human click for each normal transaction. The owner approves the operating envelope once; the agent operates within it automatically. Exceptional, out-of-policy or legally gated actions stop safely.

## Ledger model

Use integer minor units for fiat-denominated accounting and token base units for on-chain assets. Never use floating point for money. Each journal transaction must balance within one asset/currency and include:

- journal ID, idempotency key and event type;
- agent, account, principal and project references;
- source order/payment/expense and external transaction reference;
- asset, network, amount, fee and timestamps;
- debit and credit account IDs;
- evidence hash/source and verification status;
- policy version and authorization decision;
- reversal/reference fields for refunds and corrections.

Suggested account classes: external clearing, treasury available, treasury reserve, agent earned attribution, agent spendable budget, operating expense, provider/network fees, refunds/chargebacks, tax reserve and owner distribution payable. Agent earned attribution is not automatically equivalent to a legal debt or beneficial ownership; accounting treatment must be confirmed by the operator's accountant and counsel.

## Invariants

- No simulated balance can fund a real transaction.
- Pending/unconfirmed/unreconciled receipts are never spendable.
- Total agent allocations cannot exceed cleared distributable funds.
- Every spend is bound to an authenticated agent, active policy version and exact transaction terms.
- Retries are idempotent; changed terms cannot reuse an idempotency key.
- Per-transaction, daily, monthly and aggregate treasury caps are enforced atomically.
- Agent cannot change its own limits, signer, destinations, principal or policy.
- Session authority expires and can be revoked; compromised agents can be paused independently.
- No key material or recovery phrase enters model context, logs, repository or ordinary application database.
- All balances are derived from the ledger; cached balances are not authoritative.
- Reorgs, chargebacks, refunds, provider reversals and reconciliation mismatches freeze affected credits and trigger compensating entries.
- Financial execution is disabled unless legal, provider, security and owner gates for that exact flow are satisfied.

## Delivery phases

### Phase 0 — local simulation and accounting model
- Define ledger accounts, double-entry journal, allocation rules and reconciliation states.
- Build deterministic tests for balance invariants, idempotency, refunds, fees, budget reservation and audit history.
- Use synthetic balances only; keep all live adapters disabled.

### Phase 1 — agent financial identities and policy provisioning
- Bind existing cryptographic participant identities to unique account records.
- Add owner-signed, versioned financial policies and revocation.
- Validate account control without exposing private keys.
- Test delegated session-key scopes and emergency pause in a local chain simulator or test environment.

### Phase 2 — autonomous operating budgets
- Allocate only reconciled receipts into capped agent budgets.
- Add an allowlisted expense catalogue and policy-controlled spend executor.
- Demonstrate routine automated expense execution in isolated test conditions; no production funds.

### Phase 3 — legally approved live pilot
- Obtain jurisdiction-specific legal/tax advice and any required PVARA determination, licence, sandbox or no-action relief.
- Confirm payment provider and wallet eligibility, terms, AML/sanctions controls and settlement mechanics.
- Complete independent security review, key recovery rehearsal and explicit owner authorization.
- Start with one agent, one asset/network, low caps and a narrowly allowlisted expense.
- No public checkout or live transfers until every gate passes.

### Phase 4 — multi-agent economy
- Add agent-to-agent service contracts and settlement with independent evidence.
- Add cross-agent budgets, subcontracting, dispute handling and portfolio-level treasury controls.
- Federation remains separate from platform treasury ownership and requires its own legal/security review.

## Acceptance tests

The financial autonomy milestone is not complete until tests demonstrate:

1. A settled, reconciled receipt creates balanced ledger postings exactly once.
2. An unreconciled, partial, duplicated, refunded or reorged receipt cannot create spendable funds.
3. Allocation follows the exact signed policy and conserves funds.
4. Agent A cannot read or spend Agent B's budget.
5. An agent can pay an allowlisted service automatically without a per-transaction human approval.
6. A transaction above any cap, to a new destination, wrong asset/network, expired session or revoked agent is rejected.
7. Replayed requests cannot duplicate a payment; changed terms cannot reuse the same idempotency key.
8. Confirmed expenses reconcile to the exact external transaction and fees.
9. Emergency pause blocks new authorizations without corrupting historical records.
10. No secrets, private keys or recovery phrases are present in model prompts, logs, database records or source control.

## Current repository boundary

Existing components to reuse:
- cryptographic participant enrollment, key rotation and signed delegation;
- scoped capabilities and local PolicyEngine;
- append-only simulated ledger;
- routine autonomy gate and order-exposure reservations;
- provider payment adapters and gross revenue attribution prototypes;
- private Cloudflare Worker and D1 accounting tables.

Known gaps:
- no double-entry financial journal;
- no durable owner-signed financial-policy provisioning;
- no agent wallet/account registry or production signer abstraction;
- no reconciled net proceeds or spendable agent budgets;
- no autonomous expense executor or on-chain session-key enforcement;
- no live settlement, agent credit, outbound payment or verified revenue.

This document specifies the next architecture and acceptance contract. It does not enable payment processing, custody, payouts, wallet signing, production deployment or real-money execution.
