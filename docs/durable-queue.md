# Durable task queue and worker

The SQLite queue is the first persistent execution layer. It stores task definitions and status across process restarts, atomically claims one queued task at a time, records append-only task events, supports optional idempotency keys, and bounds retries (1–10 attempts).

## Run

```bash
economy enqueue "Opportunity scan" "Describe the research objective" opportunity-researcher --data-dir ./data
economy worker-once --data-dir ./data
economy tasks --data-dir ./data
economy task <task-id> --data-dir ./data
```

The built-in worker is intentionally one-shot. Run it repeatedly only under a scheduler or host you control. A local worker cannot run while the device is off or asleep. No hosted always-on worker has been provisioned by this change.

## Current limits

- SQLite is suitable for a single-host prototype; it is not a distributed queue.
- Worker claims now have a configurable lease (default 300 seconds). When a lease expires, the next claim attempt automatically requeues the task if retry budget remains, or marks it failed after the budget is exhausted. A task may be executed more than once after a crash, so task handlers must remain idempotent. Multi-host coordination and heartbeat renewal are not implemented.
- Retries are bounded; this version does not use exponential backoff.
- The included agents are deterministic local stubs. They do not browse, call an LLM, contact customers, publish listings, spend money, or move funds.
- The event table is append-only through this API, but the local database file is not tamper-proof or cryptographically signed.
- The queue is not a secure owner-approval mechanism.

Use a private data directory, protect the host, and back up the database. Never put production credentials or wallet secrets in the repository.


## Tamper-evident task event history

Task events now form a single global SHA-256 hash chain ordered by the SQLite `event_id`. Each event hash covers its ID, task ID, event type, canonical details JSON, timestamp, and previous event hash. New events are written in the same SQLite transaction as their task transition.

Use `TaskStore.verify_event_chain()` to verify the complete chain. It reports the number of checked events, the head hash, or the first failed event and reason. Legacy databases are backfilled once when all existing event hashes are absent. A partially populated chain is rejected rather than silently repaired.

**Security boundary:** this detects ordinary row edits, deletion, insertion, and reordering when the attacker cannot rewrite every dependent hash. It is not a cryptographic trust anchor against an administrator who can rewrite the database and recompute the entire chain. Stronger assurance requires regularly exporting and signing the head hash or storing it in an independently controlled append-only service. No such external checkpoint integration is enabled in this prototype.


Run the local verifier with:

```bash
economy verify-audit --data-dir ./data
```

It prints a JSON verification report and exits non-zero when verification fails.
