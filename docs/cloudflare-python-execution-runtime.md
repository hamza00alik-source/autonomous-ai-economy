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

1. An owner-authenticated, same-origin request calls `POST /v1/owner/internal-products/moba-objective-props/build`.
2. The API requires an active configured owner participant and accepts only a bounded idempotency key. It fixes the agent to `game-asset-builder` and the exact `moba_objective_props_v1` capability.
3. The D1 ledger records the owner approval and claims the job once. Repeated requests return the existing delivery record; running or failed jobs cannot be silently re-executed.
4. The JavaScript Worker calls the separate Python Worker only through a Cloudflare Service Binding. It signs the exact payload with a short-lived HMAC envelope.
5. The Python Worker validates the timestamp, signature, job/owner identifiers and exact allowlisted capability. It has no public Workers.dev endpoint, no shell, no arbitrary code loader, no external marketplace adapter and no payment or wallet capability.
6. The fixed Python producer builds the ZIP in ephemeral Worker memory/filesystem. Structural QA verifies required files, safe ZIP paths, manifest hashes and GLB headers.
7. The JavaScript Worker checks the returned job ID, QA marker, size and SHA-256, then writes the ZIP to a private R2 bucket and records `delivery_ready` in D1.

The artifact is not published, submitted, delivered to a customer, or counted as revenue. The owner can retrieve it through the bearer-authenticated `GET /v1/owner/internal-products/jobs/{job_id}/artifact` route; the route re-checks D1 ownership/state and verifies the R2 object size and SHA-256 before returning it.

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

The current API treats a successful request authenticated by the private `AAE_QUEUE_TOKEN`, with a same-origin check, as the owner's explicit approval to build this one internal product. The HMAC token between the JavaScript and Python Workers authenticates the service-to-service execution request; it is **not** a cryptographic signature by the owner. The local `OwnerApprovalStore` and `ApprovedExecutionWorker` approval verifier from the earlier prototype are not yet connected to this Cloudflare route. Before broader autonomous execution or production use, replace this shared-bearer approval boundary with a fresh, expiring, single-use owner approval bound to the job ID and action, verified and replay-protected in the cloud. Keep all other external and financial actions separately gated.

## Current limitations

- This is an owner-triggered internal product build, not an always-on queue consumer or autonomous marketplace fulfillment service.
- It supports exactly one built-in product capability.
- No general-purpose code execution, external task claims, submission, customer communication, storefront publication, checkout activation, wallet signing, transfer or spending is connected.
- Artifact retention/deletion policy and automated orphan cleanup remain to be implemented.
- No visual human review is performed. The archive's structural QA does not prove visual quality or marketplace acceptance.
- Cloudflare's in-memory filesystem is ephemeral. R2 is the durable artifact store; no artifact is stored on the Worker filesystem after the request ends.
