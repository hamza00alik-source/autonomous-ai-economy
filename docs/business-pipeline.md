# Owner business pipeline

The private owner console exposes a read-only business pipeline at `GET /v1/owner/business-pipeline?limit=20`. The route uses the existing owner bearer-token gate and requires the configured `AAE_OWNER_ID`. The limit is bounded to 1–50 records per section.

## What it reports

- Opportunity discovery: shows an owner-scoped shortlist imported from the local marketplace revenue engine. Imported rows remain untrusted source data and are always downgraded to owner-review-only in D1.
- Production: counts owner-scoped internal execution jobs by state and shows recent build records.
- Quality assurance: distinguishes structural archive QA recorded by the build worker from visual human review, which remains required.
- Listing: shows completed product-copy drafts and verification claims. Every returned draft is marked unpublished; this endpoint cannot publish.
- Checkout: reports whether the existing public checkout feature flags and provider/storage configuration enable checkout. It does not create an invoice or change a flag.
- Customer delivery: shows recent orders for the configured MOBA Objective Props product, provider status and download counts. Buyer access tokens and checkout URLs are never returned.
- Payment reconciliation: reports provider-settled gross separately from reconciled net and agent credit. A signed provider callback alone is not counted as reconciled revenue.

## Safety and limitations

The `GET` pipeline endpoint is read-only. The separate `POST` import route performs only a bounded, owner-authenticated shortlist upsert into D1. Neither route can publish listings, contact customers, create checkout invoices, deliver files, reconcile payments, transfer funds or change product execution state. The GET route returns only bounded recent records plus aggregate counts.

The cloud console currently covers one configured product, MOBA Objective Props. Marketplace discovery still runs through the local read-only scanner; `economy-revenue sync --limit 25` pushes a bounded shortlist into the cloud console. The cloud import does not run the scanner on a schedule and does not independently verify imported escrow claims. The product has structural validation but still needs visual human review, license review and market-demand validation. The endpoint is operational visibility, not evidence that the business is production-ready or earning revenue.

## API

`GET /v1/owner/business-pipeline?limit=20`

Authorization: `Authorization: Bearer <owner token>`

Response includes:
- `stages`: explicit stage states and blockers
- `opportunities`: bounded imported marketplace candidates, always marked owner-review-only
- `listing_drafts`: unpublished AI-generated listing drafts
- `builds`: recent internal build records
- `orders`: recent product orders, excluding buyer credentials
- `revenue_events`: gross, net and agent-credit states
- `controls`: read-only and non-publication guarantees

## Opportunity import API

`POST /v1/owner/revenue-opportunities/import`

Authorization: `Authorization: Bearer <owner token>`

The route accepts 1–25 validated candidates per request and upserts them by owner, source and external ID. The endpoint is owner-authenticated and request size is bounded. It rejects non-HTTPS source links, unknown fields, invalid scores, unsupported sources and oversized batches.

**Trust boundary:** every imported row is forcibly stored with `review_status='needs_owner_review'`, `independent_escrow_verified=0`, `payment_verified=0` and `claim_allowed=0`. A local scanner's escrow verification field is retained only as a source claim, not as cloud verification. The dashboard displays it as unverified. No claim, submission, payment or revenue action is available.

## Local scanner bridge

After running the read-only scanner and confirming that its local shortlist contains candidates, configure `AAE_WORKER_URL` as the private Worker HTTPS origin and `AAE_QUEUE_TOKEN` as the owner bearer token in the local environment, then run:

```bash
economy-revenue sync --limit 25
```

This command only uploads the selected shortlist to the owner dashboard. It does not trigger a scan, contact marketplaces, claim tasks or spend funds. It requires the existing private Worker to be deployed with migration `0017_revenue_opportunity_imports.sql` applied; this PR does not deploy or configure secrets.
