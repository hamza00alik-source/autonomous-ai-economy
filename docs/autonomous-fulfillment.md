# Autonomous Fulfillment Lifecycle

Status: implemented in a draft branch as a local, SQLite-backed state machine. It is not a live marketplace executor and does not claim, submit, deliver, publish, or transfer funds.

## Lifecycle

`discovered → owner_approved → in_progress → qa → delivery_ready → submission_approved → accepted → payment_pending → reconciled`

A job may be rejected or cancelled where the transition graph allows it. Skipping stages is rejected. Owner approval is required both before work begins and before an external submission is authorized.

## Identity and approval boundaries

- Job creation requires a SHA-256 public-key fingerprint and an injected identity verifier. The verifier must resolve the fingerprint against the enrolled cryptographic identity registry; a plain agent ID is not enough.
- Owner-gated transitions require an injected verifier for a signed/authorized approval token bound to the job ID and exact action.
- This branch provides the verification interfaces and tests with deterministic fakes. It does not yet wire production D1/Worker identity or owner-signature verification into the local Python runtime.
- No private key, seed phrase, wallet key or recovery phrase is requested or stored.

## Revenue recognition

The job is not revenue when discovered, approved, started, delivered, accepted, escrow-funded, invoiced, or pending payment. Reconciliation is allowed only after an injected independent provider/on-chain settlement verifier returns a verified result with net amount, currency and settlement reference. The event log records that evidence; this module does not transfer funds or allocate balances.

## Persistence and safety

- SQLite uses unique source/external IDs, transactional state transitions, unique idempotency keys and an append-only event table.
- External side effects are deliberately absent.
- Production identity/approval/settlement adapters, runtime scheduling, isolated artifact production and actual QA integration remain future work.
- The feature is local orchestration infrastructure only; no always-on cloud execution is claimed.
