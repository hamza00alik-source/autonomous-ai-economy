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

## Deploy from GitHub (phone-friendly)

The repository includes a **manual-only** GitHub Actions workflow at `.github/workflows/deploy-cloudflare-worker.yml`. It does not deploy automatically on code changes and has not been run. You can configure it from the GitHub website:

1. Create a Cloudflare account and open Workers & Pages → D1 SQL Databases. Create a database named `aae-private-ai-economy`.
2. Copy the D1 database ID.
3. In the GitHub repository, open Settings → Secrets and variables → Actions.
4. Add this repository variable:
   - `CLOUDFLARE_D1_DATABASE_ID` = the D1 database ID.
5. Add these repository secrets:
   - `CLOUDFLARE_ACCOUNT_ID` = your Cloudflare account ID.
   - `CLOUDFLARE_API_TOKEN` = a scoped token with permission to deploy Workers and manage this D1 database.
   - `AAE_QUEUE_TOKEN` = a long random owner-only API secret. Generate it with a password manager or `openssl rand -hex 32`; keep your own copy so you can call the private API.
6. In GitHub Actions, select **Deploy private Cloudflare AI worker** → **Run workflow**.

The workflow installs Wrangler, applies the D1 migration, stores `AAE_QUEUE_TOKEN` as a Cloudflare Worker secret, and deploys the Worker. It fails closed if any required value is missing. Never put secrets in repository variables, code, issues, logs, or chat.

Creating the D1 database and configuring GitHub secrets are account-owner setup steps. The workflow itself is only a deployment mechanism; it has not been triggered and no Cloudflare resource has been created by this repository change.

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

This worker only creates listing-copy drafts. The repository now includes a separate official Gumroad CLI workflow that can create an unpublished product and upload the 3D ZIP, plus a second manual workflow for explicit publication. These workflows are not automatically triggered by this Cloudflare worker. Real payment reconciliation and autonomous customer acquisition remain separate, unimplemented steps.
