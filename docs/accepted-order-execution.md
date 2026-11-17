# Accepted-order execution (local prototype)

This path connects a buyer-signed offer, provider acceptance, durable dispatch,
and the isolated worker. It is a deterministic execution-brief generator, not
a production autonomous service and not evidence of revenue.

## Run the local path

Use the same `--data-dir` for every command so agreements and the queue use
the expected database files:

1. Create and publish a service listing using the existing catalog approval flow.
2. Create a buyer-signed task offer and have the provider sign acceptance.
3. Dispatch accepted offers:

```sh
aae dispatch-accepted-orders --data-dir ./data
```

4. Execute one queued task (Linux host must have Bubblewrap and the required
   seccomp support; the worker fails closed if isolation is unavailable):

```sh
aae worker-once --data-dir ./data
```

5. Inspect the result and audit events:

```sh
aae tasks --data-dir ./data
aae task <queue-task-id> --data-dir ./data
aae verify-audit --data-dir ./data
```

Dispatch is idempotent by original order ID. It can be run repeatedly; an
accepted order is queued once. The worker produces an order-specific execution
brief containing the scope, acceptance criteria, and completion checklist.

## Continuous local mode

For a continuously running single-host prototype, start the supervisor:

```sh
python -m economy.supervisor --data-dir ./data --poll-seconds 2
```

The supervisor now reconciles accepted agreements into the durable worker queue
on every cycle before executing one queued task. Dispatch remains idempotent
across restarts. This is only always-on while that host and process remain up;
it is not hosted infrastructure, multi-host coordination, or a public service.

## Exact boundary

The current built-in order agent does **not** create the requested domain
deliverable. It creates a draft execution brief only. It does not browse, use a
paid model, contact the buyer, upload files, submit a signed work receipt, or
collect payment. Its output must never be described as completed customer work.
The existing local receipt workflow still requires actual artifact files and
the provider's signing key, then the buyer's independent verification and
acceptance. Payment remains disabled.

This prototype is not always-on: dispatch and worker commands must be run by
an operator or an explicitly configured scheduler. Do not expose the local API
or database publicly as a production service.
