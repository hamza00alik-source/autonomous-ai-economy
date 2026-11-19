# Cloud financial control foundation

## Decision

Cloudflare D1 is the intended authoritative persistence layer for **remote owner visibility and controls**. The existing Python SQLite subsystem remains the local simulation/reference implementation until a separately reviewed migration is complete. There is no bidirectional sync and no balance mirroring.

Migrations `0006_financial_control_foundation.sql`, `0007_financial_control_enforcement.sql`, and `0008_owner_key_enrollment.sql` create the additive cloud schema, enforcement triggers, and one-time owner enrollment challenge store. Worker modules now read and write these tables through authenticated owner routes and an opt-in simulated scheduler. They remain unprovisioned in production until an owner/operator enrollment ceremony, accounts, signed policies, and an explicit production deployment are completed.

## Source-of-truth boundary

- Existing local Python SQLite files remain authoritative for the current local simulated-finance CLI and scheduler.
- The new D1 tables are the authoritative cloud financial source for the new Worker control path once the migrations are applied. They are separate from the local SQLite simulation; there is no automatic sync or balance mirroring.
- Do not add dashboard balances by summing provider invoice rows or copying local SQLite snapshots into D1.
- A future cutover must be explicit and one-way: freeze local financial mutations, export and validate a reviewed snapshot if migration is desired, then activate the cloud authority. Never run both ledgers as writable authorities.
- The dashboard reports only D1 cloud records. It does not claim that local SQLite policies, ledger, budgets or schedules are synchronized.

## Cloud schema

| Area | Tables | Purpose |
|---|---|---|
| Participants and accounts | `financial_participants`, `financial_accounts` | Owner/operator/agent status with explicit owner-to-operator-to-agent binding, public verification keys, currency-specific accounts |
| Double-entry journal | `financial_journal_transactions`, `financial_journal_postings` | Immutable posted transactions and integer minor-unit debit/credit lines |
| Receipts | `financial_settlement_receipts` | Provider-scoped unique receipt reference, expected gross/fee, evidence metadata and reconciliation lifecycle |
| Authorization | `financial_policies` | Versioned canonical policy payload, operator signer ID, owner signature and public-key fingerprint; private keys are never stored |
| Spending | `financial_budget_reservations`, `financial_expense_schedules` | Idempotent reservations, policy-version pinning and bounded recurring schedules |
| Audit | `financial_audit_events` | Append-oriented record of owner/agent financial-control changes |

The schema uses integer minor units, exact three-letter uppercase currency codes, foreign keys, unique idempotency/source references, constrained lifecycle states, and bounded schedule intervals. Each agent is bound to an owner and an operator; each operator is bound to an owner. Signed policy versions record the exact operator signer. Database triggers reject updates/deletes to posted journal transactions, postings and audit events, and reject posting currency mismatches. These constraints are necessary but not sufficient: Worker code must still validate participant types, signatures, destination allowlists, policy state, balances and posting totals. The database does not independently prove that every transaction's posting group balances.

## Policy signature verification foundation

`cloudflare/worker/src/financial_policy_auth.js` now provides a fail-closed Ed25519 verifier for canonical policy payloads. It checks the exact policy schema, safe integer limits, non-wildcard exact destination allowlists, owner/operator/agent active status and relationship, public-key fingerprint, signature encoding, and the signature over canonical JSON bytes. Its D1 loader cross-checks the signed payload against stored columns and the joined participant records. The private key is never accepted by the verifier or stored in D1. Tests cover valid signatures, altered payloads, wrong/suspended signers, owner-agent mismatch, malformed policies and D1 loading.

`cloudflare/worker/src/financial_ledger.js` adds a separate internal journal-posting primitive. It validates balanced integer-minor-unit postings, rejects duplicate account lines and unsafe amounts, checks account owner/currency/status, then writes the transaction, posting lines and audit event in one D1 batch. It uses a payload hash with a unique idempotency key and resolves uncertain duplicate outcomes by reading back the original record. Database triggers additionally require an active owner, same-owner active accounts and an active owner-scoped audit actor. Dedicated unit tests exercise validation, account rejection, single-batch composition, idempotent replay and ambiguous duplicate retries.

The policy verifier and base journal writer remain internal modules. The policy-enforced cloud control service and authenticated owner endpoints are now implemented separately below. No participant or policy rows are seeded, and the remote owner signing/provisioning workflow remains a prerequisite to activation.

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

1. Validate this migration against SQLite/D1-compatible SQL and schema tests. The repository now has a Python SQLite migration test suite for participant binding, append-only ledger/audit rows, policy versioning, account/currency guards and owner-scoped audit actors.
2. Implement read-only owner APIs for cloud participant/policy/account/schedule inventory only after the cloud schema and authorization model are reviewed.
3. Implement cloud ledger writes with atomicity, concurrency, idempotency, signature and audit tests.
4. Add a read-only cloud dashboard view and reconcile it against authoritative D1 rows.
5. Implement owner signing and emergency controls.
6. Only after explicit owner approval and legal/provider clearance consider any live settlement or transfer integration.

No production deployment, migration application, live checkout, payment provider call, wallet signing, transfer, or money movement is part of this change.


## Cloud policy-enforced controls implementation

The cloud service layer now includes `cloudflare/worker/src/financial_controls.js`:

- `getCloudFinancialControls` returns owner-scoped budgets, reservations, schedules and occurrence history. Available balances are calculated from posted agent-operating journal credits minus debits and active reservations; no local SQLite balances are copied.
- `reserveCloudAgentBudget` re-verifies the active Ed25519-signed policy, owner/operator/agent relationship, currency, exact destination and per-transaction cap before attempting an idempotent reservation. D1 triggers independently enforce the emergency-pause state, daily cap and available budget under concurrent requests.
- `settleCloudAgentExpense` re-verifies the policy and posts the debit, expense credit, audit event and reservation settlement in one D1 batch. This is an internal simulated accounting event only; it never contacts a provider or signs/broadcasts a transfer.
- `createCloudExpenseSchedule` pins each recurring schedule to the exact signed policy version. Schedule pause/resume/cancel operations are owner-only and audited.
- `runDueCloudExpenseSchedules` claims unique schedule occurrences, creates idempotent reservations, and settles only through the same policy-enforced journal path. Blocked occurrences remain retryable; due dates advance only after successful settlement.
- Worker cron invokes this scheduler only when both `AAE_CLOUD_FINANCIAL_SCHEDULER_ENABLED=true` and `AAE_OWNER_ID` are configured. It is not enabled by default.

Migration `0007_financial_control_enforcement.sql` adds owner emergency-pause state and unique recurring occurrence records. Database triggers enforce signed-policy row state, exact destination allowlists, per-transaction ceilings, daily reserved-plus-settled spending ceilings, active same-owner participants, available agent operating budget, and an explicit owner unpause before any reservation. Reservation settlement requires its matching expense journal transaction. A paused owner blocks both new reservations and journal settlement.

Authenticated owner routes now expose `GET /v1/owner/financial-controls`, `POST /v1/owner/financial-controls/policies` for locally signed policy registration, emergency pause/resume, and recurring schedule create/pause/resume/cancel. Mutation routes require the existing bearer authorization, same-origin JSON requests, bounded bodies, and an `AAE_OWNER_ID` binding. The mobile owner dashboard displays cloud agent budgets, durable reservations, recurring schedules, and an emergency pause control.

## Provisioning and activation gate

This is implemented code, not an activated cloud financial system. No cloud owner/operator/agent participants, public keys, signed policy rows, accounts or budgets are seeded. Consequently the owner controls API returns unavailable until a valid `AAE_OWNER_ID` is provisioned, and spending remains paused by default. A secure, reviewed owner enrollment and local-device policy-signing/provisioning workflow is still required before an owner can create signed cloud policies. The cron flag and owner binding have not been configured in production. The migration has not been applied to production D1, and the Worker/dashboard have not been deployed.

The existing global bearer token remains the API gate in this prototype; before production activation, replace or formally bind it to an owner-specific credential, add rate limiting and audit/alerting for control mutations, and complete a security review. Do not treat the dashboard's simulated expense settlement as a real payment.


The policy registration endpoint accepts only the canonical policy object, canonical payload, Ed25519 signature and signer public-key fingerprint. It looks up the enrolled operator public key in D1, re-verifies the exact owner → operator → agent relationship and signature, enforces strictly increasing policy versions, supersedes the prior active version atomically, and appends an audit event. It never accepts or stores private key material. The Android dashboard provides a paste-in signed-envelope field; generating/signing that envelope still requires the owner's local signing workflow and an already enrolled public key.


Important compatibility note: the existing local SQLite policy store is a separate subsystem and its current policy payload/signature format is not automatically a cloud policy envelope. Do not paste a local SQLite policy record into the cloud registration form unchanged. The cloud signer/export bridge must produce the exact cloud canonical policy schema and bind it to the enrolled cloud operator public key; that bridge and initial participant/account provisioning are still outstanding.

## Local cloud-policy signing/export bridge

`economy-finance cloud-policy-sign` creates the exact signed envelope accepted by `POST /v1/owner/financial-controls/policies`. It is a local-only operation:

- The input is the cloud policy schema (exactly the eight fields accepted by the Worker; it is intentionally not the local SQLite policy object, which includes a separate `schema` field).
- The command checks that the owner is active in the local participant registry, the agent is active and locally operated by that owner, and the supplied Ed25519 private key derives exactly the owner's already-enrolled local public key.
- It signs canonical JSON, derives the Ed25519 public JWK fingerprint, and exports only the policy, canonical payload, signature and fingerprint.
- The output file is created exclusively; it refuses to overwrite an existing file. The private key is never serialized into the envelope, uploaded, printed or stored by AAE.
- `--operator-id` must be the pre-enrolled cloud operator participant ID whose D1 public JWK is bound to the same public key as the local owner key.

Example (run only on a trusted machine that already holds the owner's PEM key):

```sh
economy-finance --data-dir ./data cloud-policy-sign ./cloud-policy.json \
  --private-key /secure/path/owner-ed25519.pem \
  --operator-id operator-01 \
  --output ./cloud-policy-envelope.json
```

The cloud owner/operator enrollment ceremony is still a prerequisite: this command does not create cloud identities, upload public keys, or provision agent records. Do not upload a local SQLite policy export as if it were a cloud envelope. The Android dashboard accepts the resulting signed envelope, but the user must protect the local key file and review the exact policy terms before signing.

## Owner/operator enrollment

Migration `0008_owner_key_enrollment.sql` adds a short-lived, single-pending-challenge enrollment ceremony. The authenticated owner obtains a five-minute challenge from `GET /v1/owner/financial-controls/enrollment/challenge`; the browser signs a canonical proof with an Ed25519 private key, then submits only the public JWK, signature, selected local agent IDs and supported currency codes to `POST /v1/owner/financial-controls/enrollment/complete`.

The owner and operator IDs are configured out of band using Worker variables `AAE_OWNER_ID` and `AAE_OPERATOR_ID`. Enrollment verifies proof of possession before creating an owner, operator, owner-bound agents, empty ledger accounts and an emergency-pause row. It is idempotent for the exact completed challenge and rejects key/identity conflicts. All new cloud spending remains paused. The enrollment proves control of a signing key and an authenticated owner session; it is not government identity verification, KYC/AML clearance, or authorization to operate a regulated payment service.

The Android-friendly owner dashboard supports:
- Generate a new Ed25519 key in the browser, or import an existing unencrypted PKCS#8 PEM key.
- Keep the private key in browser-tab memory only; it is never sent to the Worker or saved in browser storage.
- Download a private-key backup when generating a new key. The owner must protect this file; losing it means losing the ability to sign future policies unless a separately authorized key-rotation/recovery process is completed.
- Sign the enrollment challenge and subsequent cloud policy JSON locally in the browser.
- Submit only public key material, canonical policy data and signatures to authenticated same-origin endpoints.

WebCrypto Ed25519 support is required. If the browser does not support it, the dashboard fails closed; the local `economy-finance cloud-enrollment-sign` and `cloud-policy-sign` commands are available on a trusted machine instead. Neither workflow uploads private key material.

The current cloud ledger accepts only three-letter uppercase currency codes. This is suitable for USD-denominated accounting but does not yet represent four-letter stablecoin assets such as USDC/USDT. Do not label USD ledger balances as stablecoin balances or enable crypto asset allocations until asset-code support and provider settlement mapping are separately implemented and tested.
