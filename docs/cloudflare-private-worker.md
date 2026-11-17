# Private Cloudflare AI worker

## Purpose and boundary

This is a separate, deployable, private scheduled worker for the first AI product-copy participant. It uses:
- Cloudflare Workers Free for the HTTPS API and five-minute Cron Trigger;
- Cloudflare D1 Free for a small private task queue and daily usage reservations;
- the Workers AI binding with the fixed `@cf/zai-org/glm-4.7-flash` model.

It is deliberately narrow. It can accept product facts, draft and validate listing copy, and return the draft to the owner. It cannot publish products, upload files, contact customers, create payments, hold funds, or move money. It does not connect to the Python local SQLite queue. This is an independently hosted first worker lane, not the entire AI economy.

## Free-plan constraints checked 17 November 2026

Cloudflare currently documents:
- Workers Free: 100,000 requests/day and 10 ms CPU per invocation;
- up to 5 Cron Triggers per account;
- D1 Free: 5 million rows read/day and 100,000 rows written/day;
- Workers AI: 10,000 neurons/day free allocation, with this worker reserving at most 6,500 estimated neurons/day.

These quotas can change and may be shared with other projects on the same Cloudflare account. The 6,500 limit is a conservative local estimate, not provider metering or a guarantee that Cloudflare will accept every request. Monitor the Cloudflare usage dashboard. If a quota is reached, work pauses or requests fail; do not upgrade to a paid plan without explicit approval.

Sources:
- https://developers.cloudflare.com/workers/platform/limits/
- https://developers.cloudflare.com/workers/platform/pricing/
- https://developers.cloudflare.com/workers/configuration/cron-triggers/
- https://developers.cloudflare.com/workers-ai/platform/pricing/

## Deploy

Requires a Cloudflare account. Do not paste tokens into chat or commit them.

1. On a computer with Node.js 22+, open this directory:

   `cd cloudflare/worker`

2. Install the pinned Wrangler development dependency:

   `npm install`

3. Authenticate Wrangler with your own Cloudflare account:

   `npx wrangler login`

4. Create the D1 database:

   `npx wrangler d1 create aae-private-ai-economy`

5. Copy the returned database ID into `wrangler.toml`, replacing `REPLACE_WITH_D1_DATABASE_ID`.

6. Apply the initial schema:

   `npx wrangler d1 migrations apply aae-private-ai-economy --remote`

7. Create a long random queue token locally and store it as a Worker secret:

   `npx wrangler secret put AAE_QUEUE_TOKEN`

   Never put this value in source control, an issue, a log, or chat. Treat it as an owner-only API credential.

8. Deploy:

   `npx wrangler deploy`

The deployment URL is shown by Wrangler. The scheduled trigger runs every five minutes. The worker will remain idle until an authenticated task is queued.

## API

All private endpoints require `Authorization: Bearer <AAE_QUEUE_TOKEN>`.

- `GET /health` — public liveness response; reveals no account or queue information.
- `GET /v1/status` — private task counts and daily reserved-neuron counter.
- `POST /v1/tasks/product-copy` — private enqueue endpoint; body is the product facts JSON. Repeated identical facts are idempotent.
- `GET /v1/tasks/product-copy/{task_id}` — private task status and completed draft.

Example enqueue body: `products/moba-objective-props/product-facts.json`.

The API accepts at most 8 KB of facts. It has one private bearer credential, not public user registration or multi-tenant participant identity. Keep the URL and token private. Rotate the token if exposed.

## Failure and recovery

- Each task is claimed once; there are no automatic inference retries.
- If the worker is interrupted while running, it becomes `stalled` after 15 minutes. Inspect it rather than replaying automatically, because the model may already have consumed quota.
- Model errors mark the task failed and retain the estimated usage reservation.
- The daily budget table resets by UTC date; Cloudflare's own quota enforcement and dashboard remain authoritative.
- D1 backups/export and secret rotation must be arranged before production customer data is stored.

## Current limitation

This worker only creates listing-copy drafts. Gumroad's official help centre says product creation and content upload are not available through its API, so this worker cannot publish or upload the actual 3D ZIP. A storefront upload workflow and real payment reconciliation remain separate, unimplemented steps.
