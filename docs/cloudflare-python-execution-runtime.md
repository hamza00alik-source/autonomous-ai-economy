# Private Cloudflare Python execution runtime

Status: implementation PR only. The runtime has not been deployed, the R2 bucket has not been created, and no production secret has been provisioned.

## Why a separate Python Worker

The existing private API is a JavaScript Cloudflare Worker. The approved product producer is Python. Cloudflare's Python Workers runtime executes Python through Pyodide and supports the Python standard library, including the modules used by the deterministic GLB/Godot pack builder. This keeps the canonical Python producer instead of rewriting or duplicating it in JavaScript.

References:
- https://developers.cloudflare.com/workers/languages/python/
- https://developers.cloudflare.com/workers/languages/python/stdlib/
- https://developers.cloudflare.com/workers/languages/python/ffi/

The runtime package is prepared from the canonical `src/economy/game_asset_pack.py` by `tools/prepare_cloudflare_python_runtime.py`. Generated copies under `cloudflare/python-runtime/python_modules` are ignored by Git.

## Request and execution boundary

1. The owner console requests a fresh challenge from `POST /v1/owner/internal-products/moba-objective-props/approval-challenge` and signs the exact canonical payload locally with the enrolled Ed25519 key.
2. An owner-authenticated, same-origin request calls `POST /v1/owner/internal-products/moba-objective-props/build` with the five-minute, single-use signature. The API verifies the owner, action, exact agent, exact product capability, idempotency key, nonce and expiry; D1 consumes the nonce.
3. The API persists an `approved` job and append-only owner approval event in D1, then returns HTTP 202. The request does not run the Python producer synchronously.
4. The existing five-minute Cloudflare Cron trigger polls the D1 queue. It atomically claims one eligible job, writes an execution-start event, and uses a ten-minute lease. Expired leases can be reclaimed, with a maximum of three claims; exhausted leases become terminal failures.
5. The JavaScript Worker calls the separate Python Worker only through a Cloudflare Service Binding. It signs the exact payload with a short-lived HMAC envelope.
6. The Python Worker validates the timestamp, signature, job/owner identifiers and exact allowlisted capability. It has no public Workers.dev endpoint, no shell, no arbitrary code loader, no external marketplace adapter and no payment or wallet capability.
7. The fixed Python producer builds the ZIP in ephemeral Worker memory/filesystem. Structural QA verifies required files, safe ZIP paths, manifest hashes and GLB headers.
8. The JavaScript Worker checks the returned job ID, QA marker, size and SHA-256, then writes the ZIP to a private R2 bucket and records `delivery_ready` in D1. The owner dashboard polls the owner-authenticated status route and enables download only when ready.

The artifact is not published, submitted, delivered to a customer, or counted as revenue. The owner can retrieve it through the bearer-authenticated `GET /v1/owner/internal-products/jobs/{job_id}/artifact` route; the route re-checks D1 ownership/state and verifies the R2 object size and SHA-256 before returning it.

## Owner queue observability

The private owner console at `/owner` includes read-only execution operations visibility when connected with the existing owner bearer token:

- `GET /v1/owner/internal-products/operations?limit=25` returns per-status counts, the newest bounded set of jobs, execution attempt counts, lease expiry, artifact digest/size, error codes, retention-review timestamps, and recent append-only audit events.
- The response is scoped to the configured `AAE_OWNER_ID`; the route is behind the owner bearer-token authorization gate. Limits are bounded to 1–100 jobs and at most 200 recent events.
- The console shows approved/queued, running, delivery-ready and failed totals, job details and event evidence. Invalid event JSON is shown as unavailable rather than breaking the dashboard.
- The console's artifact scan calls the existing read-only `GET /v1/owner/internal-products/artifacts/inventory` endpoint. It reports one R2 page at a time and exposes the next-page cursor; it does not change R2, D1 or audit records.
- Refresh and artifact scans are observational only. They do not claim, retry, cancel, delete, publish, contact customers or spend funds.

This is operational visibility, not an autonomous recovery control plane. Failed jobs require investigation; no automatic retry or lease extension is exposed in the console.

## Required configuration before any deployment

These are manual owner-controlled prerequisites. This PR does not create resources, deploy services, or set secrets.

- Create the private R2 bucket named `aae-private-execution-artifacts` in the Cloudflare account. Do not enable public access or a public custom domain.
- Provision the same high-entropy `AAE_EXECUTION_BRIDGE_SECRET` independently as a Cloudflare Worker secret on both `autonomous-ai-economy-private-worker` and `aae-python-execution-runtime`. Do not put it in source code, ordinary Wrangler vars, GitHub Actions, chat, or logs.
- Confirm `AAE_OWNER_ID` maps to an active `owner` participant in D1.
- Confirm the configured Cloudflare API token has only the required Worker, D1 migration, Service Binding, and R2 permissions.
- Deploy the Python Worker first, then the private JavaScript Worker, only after explicit owner approval.
- Measure actual CPU use against the account's plan before relying on cloud generation. Python Workers run in Pyodide; the geometry generation and ZIP QA may exceed the Free plan's CPU budget. Do not upgrade or incur charges without explicit approval.
- Run a private end-to-end test and verify the R2 object is private, the D1 event trail is complete, and no public route can retrieve the artifact.

## Owner authorization distinction

The cloud build route now requires a fresh Ed25519 owner signature over a canonical approval payload. The payload binds the owner, the `execute_internal_product` action, exact `game-asset-builder` agent, exact `moba_objective_props_v1` spec, idempotency key, nonce, issue time and five-minute expiry. `POST /v1/owner/internal-products/moba-objective-props/approval-challenge` returns the canonical payload and public key; the owner signs the canonical payload locally and submits `{ idempotency_key, approval: { canonical_payload, signature } }` to the build route. The cloud verifies against the enrolled owner public key and consumes the nonce in D1; nonce records are immutable and unique per owner. Replays and changed scopes fail closed. The bearer token remains an additional API access gate, not the approval itself. The HMAC between Workers authenticates only the service-to-service bridge. This authorizes only the exact internal build; publication, external submission, customer contact, payments and transfers remain separately gated.

## Current limitations

- This is an owner-authorized, cron-scheduled internal product queue, not a continuously running queue consumer or autonomous marketplace fulfillment service. The configured cron cadence is five minutes; actual execution remains subject to Cloudflare Worker limits and account quotas.
- It supports exactly one built-in product capability.
- No general-purpose code execution, external task claims, submission, customer communication, storefront publication, checkout activation, wallet signing, transfer or spending is connected.
- Private artifacts receive a `retention_review_after` timestamp 90 days after reaching `delivery_ready`. This is a review date, not automatic expiry: downloads remain available until a separate owner-approved deletion process is implemented. The migration does not delete R2 objects, D1 job records, or append-only audit events. Automated orphan detection and cleanup remain unimplemented.
- No visual human review is performed. The archive's structural QA does not prove visual quality or marketplace acceptance.
- Cloudflare's in-memory filesystem is ephemeral. R2 is the durable artifact store; no artifact is stored on the Worker filesystem after the request ends.


## Private artifact retention policy

Migration `0016_artifact_retention_review.sql` adds a 90-day review marker to internal execution jobs. Existing delivered artifacts are backfilled; newly delivered artifacts receive the marker when their status changes to `delivery_ready`.

The marker is deliberately non-destructive. It does not expire downloads, delete R2 objects, remove D1 records, or alter append-only execution events. After the review date, an owner must decide whether an artifact should be retained or deleted. A future deletion feature must independently verify owner authorization, confirm the exact artifact key and digest, preserve the audit trail, and handle R2/D1 partial failures safely. No scheduled or background cleanup is authorized by this change.

Orphan detection is available as a read-only owner endpoint: `GET /v1/owner/internal-products/artifacts/inventory?limit=100`. It lists one R2 page under `internal-products/`, reconciles each object key against D1, reports objects without a D1 artifact record as `review_only` orphan candidates, and flags status/metadata/size mismatches. Use the returned `next_cursor` to inspect subsequent pages. The endpoint never deletes objects, changes metadata, or mutates D1. It requires the owner bearer token and a configured private R2 binding. This is an inventory, not a cleanup operation; any deletion must remain a separate explicitly approved process.
