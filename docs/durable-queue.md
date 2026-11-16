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
- A process crash after claiming a task can leave it marked `running`. Automatic lease recovery and multi-host coordination are not implemented yet.
- Retries are bounded; this version does not use exponential backoff.
- The included agents are deterministic local stubs. They do not browse, call an LLM, contact customers, publish listings, spend money, or move funds.
- The event table is append-only through this API, but the local database file is not tamper-proof or cryptographically signed.
- The queue is not a secure owner-approval mechanism.

Use a private data directory, protect the host, and back up the database. Never put production credentials or wallet secrets in the repository.
