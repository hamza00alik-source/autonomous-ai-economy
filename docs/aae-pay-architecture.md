# AAE Pay: Native Payments and Settlement Architecture

Status: **design only — not a payment processor, wallet custodian, or production money movement system**

## Objective

Build AAE-owned payment software and accounting workflows so the Autonomous AI Economy owns its invoices, order/payment state, double-entry ledger, agent earnings attribution, fee policy, reconciliation, treasury reporting, and payment adapters.

Owning the software does not mean owning the rails. Actual money still moves through an underlying payment network, bank, or blockchain. Any customer-facing payment service, custody, exchange, transfer, token issuance, or similar regulated activity must be assessed and authorized before it is offered.

## Product name

**AAE Pay** — internal working name. No public brand or service launch is implied.

## Design principles

1. **Ledger first, rails second.** AAE's authoritative accounting journal is separate from external payment observations.
2. **Double-entry and append-only.** Each posting balances; immutable journal entries are never silently edited. Corrections use reversals and new entries.
3. **No invented funds.** A pending payment, invoice, escrow, provider callback, local balance, or unverified transaction cannot be recorded as settled revenue.
4. **External evidence is independently verified.** Verify payment through a trusted rail source; callbacks are signals, not proof.
5. **Idempotency.** Each external payment observation and posting has a unique key; duplicate notifications cannot credit twice.
6. **Segregation of funds.** Customer money, agent payable balances, platform revenue, refunds, fees, and treasury funds are distinct accounts/records.
7. **Least privilege and human approval.** External transfer, refund, treasury movement, payout, custody activation, production secrets, or service launch require explicit owner approval and legal review.
8. **Never expose signing material.** Private keys, seed phrases, and recovery secrets must never be requested, logged, or stored in chat.
9. **No fake agent economy.** Internal agent credits are accounting liabilities/credits only; they do not represent cash or transferable token value unless legally authorized and backed.
10. **Traceability.** Every transaction links invoice, customer/order, payment evidence, journal posting, delivery, fee, refund, and reconciliation records.

## Proposed components

- Invoice and order service: immutable invoice ID, amount, currency, expiration, line items, and buyer-visible terms.
- Payment method registry: only methods enabled for the applicable jurisdiction and activity.
- Payment observer: read-only rail/network data ingestion; retains raw evidence hash and observation timestamp.
- Verification policy: network, asset/token identifier, destination, amount, confirmation/finality policy, and transaction uniqueness.
- Double-entry journal: accounts, balanced postings, idempotency keys, reversal references, currency precision.
- Agent attribution: calculates proposed earning splits only from accepted work and reconciled net receipt.
- Refund workflow: approval-gated, linked to original payment and reversal entries; no automated transfer in initial scope.
- Treasury view: balance snapshots, liabilities, customer funds, agent payable, platform income, pending, and reconciled amounts.
- Reconciliation engine: compares payment observations, ledger, delivery state, fee schedules, and external settlement.
- Adapter interface: future rail-specific adapters must be isolated and replaceable; no provider dependency in core ledger logic.

## Transaction lifecycle

created -> awaiting_payment -> observed_pending -> verified_settled -> reconciled -> delivered

Exceptional states: expired, underpaid, overpaid, duplicate_observation, verification_failed, refund_review, reversed, disputed.

The lifecycle must not skip verification. Delivery policy is separate from payment status; a policy may allow delivery only after verified settlement, and exceptions require explicit approval and audit.

## Example accounting (illustrative only)

Customer pays 10.00 units; assumed fee 1.00; agent payable 9.00.

On verified receipt (assuming funds are controlled and the accounting treatment has been reviewed):
- Debit external settlement asset: 10.00
- Credit customer/payment clearing: 10.00

After reconciliation:
- Debit customer/payment clearing: 10.00
- Credit platform fee revenue: 1.00
- Credit agent payable: 9.00

This is illustrative and not a prescribed treatment. Actual journal accounts depend on legal entity, custody/control, contract, taxes, fees, and accounting advice. Never treat customer or agent funds as platform revenue.

## Phased roadmap

### Phase 0 — design and legal classification (this document)
- Map payment flows, participants, countries, assets, custody/control, service categories, and planned monetization.
- Get qualified counsel and regulator guidance before any real-money functionality.

### Phase 1 — non-money internal ledger prototype
- Build invoices and simulated payments for tests.
- Use clearly marked SIMULATED events and non-transferable internal agent accounting.
- Double-entry validation, idempotency, audit history, reversals, reconciliation, test vectors, and owner dashboard.
- No real deposits, withdrawals, custody, exchange, payment processing, public balances, or token.

### Phase 2 — evidence-only payment observer
- After legal review, connect read-only payment evidence to an authorized existing rail.
- Confirm chain/network/token contract/destination/amount/confirmation and transaction uniqueness.
- No signing, custody, sweep, forwarding, or payout functionality.

### Phase 3 — controlled settlement integration
- Only after authorization, operational security review, accounting review, and explicit owner approval.
- Transfer/refund/payout APIs are disabled by default, separated from the observer, allowlisted, bounded, and audited.

### Phase 4 — independent payment service/network
- Separate business plan, licensing, capital, compliance, banking/settlement, AML/CFT, sanctions, customer support, dispute handling, safeguarding, cybersecurity, and operational risk review.
- Do not launch or solicit users until authorization and prerequisites are proven.

## Regulatory gate

This project is not legal advice. Before any crypto payment, custody, transfer, exchange, issuance, or customer-facing payment service is activated, obtain qualified local counsel and contact the relevant regulator(s), including PVARA where applicable. Confirm exact license categories, scope, entity/capital requirements, sandbox eligibility, AML/CFT, sanctions, tax, record retention, consumer protection, and cross-border rules. Do not assume an internal ledger or self-hosted software removes regulatory obligations.

## Initial non-money acceptance criteria

- All test postings balance to zero per transaction/currency.
- Currency precision and overflow are validated.
- Duplicate invoice, observation, or posting IDs cannot create duplicate credit.
- A callback/provider claim cannot mark payment verified.
- Simulated events are unmistakably labeled and excluded from revenue reporting.
- Reversal is append-only and references original entries.
- Agent payable, customer liabilities, fees, and revenue are separate.
- No transfer, wallet signing, token, public checkout, or custody capability exists in Phase 1.
- Owner dashboard read-only; all financial mutation tests require explicit owner authorization.
- CI covers ledger invariants, replay, duplicate observations, invalid currencies/amounts, concurrent posting, and reversals.

## Explicit non-goals for the initial build

- Issuing a stablecoin or token
- Creating a transferable stored-value balance
- Operating an exchange
- Custody or key management for customers
- Bank/card processing
- Money transmission or cross-border remittance
- Automatic withdrawals, refunds, payouts, or treasury transfers
- Public payment-service launch
