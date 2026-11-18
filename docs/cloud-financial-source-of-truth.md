# Cloud financial control foundation

## Decision

Cloudflare D1 is the intended authoritative persistence layer for **remote owner visibility and controls**. The existing Python SQLite subsystem remains the local simulation/reference implementation until a separately reviewed migration is complete. There is no bidirectional sync and no balance mirroring.

Migration `0006_financial_control_foundation.sql` is an additive schema foundation only. It creates empty tables and indexes; it does not copy local data, create participants/accounts/policies, expose routes, enable payments, or execute financial activity.

## Source-of-truth boundary

- Existing local Python SQLite files remain authoritative for the current local simulated-finance CLI and scheduler.
- The new D1 tables are an empty future cloud authority. They are not yet read or written by Worker code.
- Do not add dashboard balances by summing provider invoice rows or copying local SQLite snapshots into D1.
- A future cutover must be explicit and one-way: freeze local financial mutations, export and validate a reviewed snapshot if migration is desired, then activate the cloud authority. Never run both ledgers as writable authorities.
- Until cutover, the dashboard must continue to say that local policy, ledger, budgets and schedules are unavailable remotely.

## Cloud schema

| Area | Tables | Purpose |
|---|---|---|
| Participants and accounts | `financial_participants`, `financial_accounts` | Owner/operator/agent status, public verification keys, currency-specific accounts |
| Double-entry journal | `financial_journal_transactions`, `financial_journal_postings` | Immutable posted transactions and integer minor-unit debit/credit lines |
| Receipts | `financial_settlement_receipts` | Provider-scoped unique receipt reference, expected gross/fee, evidence metadata and reconciliation lifecycle |
| Authorization | `financial_policies` | Versioned canonical policy payload, owner signature and public-key fingerprint; private keys are never stored |
| Spending | `financial_budget_reservations`, `financial_expense_schedules` | Idempotent reservations, policy-version pinning and bounded recurring schedules |
| Audit | `financial_audit_events` | Append-oriented record of owner/agent financial-control changes |

The schema uses integer minor units, exact three-letter uppercase currency codes, foreign keys, unique idempotency/source references, constrained lifecycle states, and bounded schedule intervals. Database triggers reject updates/deletes to posted journal transactions, postings and audit events, and reject posting currency mismatches. These constraints are necessary but not sufficient: Worker code must still validate participant types, signatures, destination allowlists, policy state, balances and posting totals. The database does not independently prove that every transaction's posting group balances.

## Required transaction protocol before enabling writes

Cloudflare D1 writes must use a single atomic `DB.batch([...])` for each logical financial transition. Do not implement a read-check-write sequence split across independent requests.

1. Validate authenticated owner scope, active owner/operator/agent relationship, current public key and owner signature.
2. Validate canonical policy bytes, monotonic version, exact destination and currency, per-transaction and UTC-day limits.
3. Use conditional SQL updates/inserts inside the same batch to reserve available agent funds and enforce daily spend ceilings. A stale pre-read must never authorize a debit.
4. Insert the journal transaction and all posting lines in that same batch. Application validation must prove debit total equals credit total for each currency before submitting the batch.
5. Use unique idempotency keys and unique source references so retrying a completed operation cannot create duplicate debits, credits or expense occurrences.
6. Append an audit event in the same batch as the state transition.
7. Treat an uncertain batch result as unknown until the idempotency key and persisted state are read back. Never retry under a new key.

D1 does not provide a deferred SQL constraint that automatically proves a group of posting rows balances. That invariant must be checked in trusted Worker code before the atomic batch; all balance-affecting writes must be confined to that path. Direct table writes, ad-hoc SQL mutation and dashboard-side calculations are prohibited.

## Receipt trust requirements

A receipt may move to `confirmed` only after a provider-specific verifier validates the authentic callback or a provider API lookup. Persist a hash/reference for evidence, not secrets. Validate provider identity, invoice/order binding, amount, currency, finality/status, fees and duplicate event handling. A caller-supplied status string or a browser request is never settlement proof. Refunds, chargebacks and reversals require compensating journal entries; posted journal rows are not edited or deleted.

## Owner signing and security

- Owner signing keys stay on the owner's device. Store only public verification material and signature evidence in D1.
- Do not upload PEM/private keys, seed phrases, recovery codes or provider credentials.
- A future mobile signing experience must prove the exact canonical bytes being signed, key ownership, browser cryptographic compatibility and recovery/rotation behavior before implementation.
- Keep the current bearer-authenticated read-only dashboard unchanged until scoped owner authorization, CSRF/origin protections, audit coverage, rate limits and concurrency tests exist.
- Emergency pause must be enforceable by the Worker at the point where a due action is claimed, not just by a UI flag.

## Rollout gates

1. Validate this migration against SQLite/D1-compatible SQL and add schema tests.
2. Implement read-only owner APIs for cloud participant/policy/account/schedule inventory only after the cloud schema and authorization model are reviewed.
3. Implement cloud ledger writes with atomicity, concurrency, idempotency, signature and audit tests.
4. Add a read-only cloud dashboard view and reconcile it against authoritative D1 rows.
5. Implement owner signing and emergency controls.
6. Only after explicit owner approval and legal/provider clearance consider any live settlement or transfer integration.

No production deployment, migration application, live checkout, payment provider call, wallet signing, transfer, or money movement is part of this change.
