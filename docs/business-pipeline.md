# Owner business pipeline

The private owner console exposes a read-only business pipeline at `GET /v1/owner/business-pipeline?limit=20`. The route uses the existing owner bearer-token gate and requires the configured `AAE_OWNER_ID`. The limit is bounded to 1–50 records per section.

## What it reports

- Opportunity discovery: explicitly reports `not_connected`. The local marketplace revenue-engine scan is not represented as a live cloud feed.
- Production: counts owner-scoped internal execution jobs by state and shows recent build records.
- Quality assurance: distinguishes structural archive QA recorded by the build worker from visual human review, which remains required.
- Listing: shows completed product-copy drafts and verification claims. Every returned draft is marked unpublished; this endpoint cannot publish.
- Checkout: reports whether the existing public checkout feature flags and provider/storage configuration enable checkout. It does not create an invoice or change a flag.
- Customer delivery: shows recent orders for the configured MOBA Objective Props product, provider status and download counts. Buyer access tokens and checkout URLs are never returned.
- Payment reconciliation: reports provider-settled gross separately from reconciled net and agent credit. A signed provider callback alone is not counted as reconciled revenue.

## Safety and limitations

The endpoint is read-only. It cannot publish listings, contact customers, create checkout invoices, deliver files, reconcile payments, transfer funds or change product state. It returns only bounded recent records plus aggregate counts.

The cloud console currently covers one configured product, MOBA Objective Props. Opportunity discovery is still a separate local revenue-engine workflow. The product has structural validation but still needs visual human review, license review and market-demand validation. The endpoint is operational visibility, not evidence that the business is production-ready or earning revenue.

## API

`GET /v1/owner/business-pipeline?limit=20`

Authorization: `Authorization: Bearer <owner token>`

Response includes:
- `stages`: explicit stage states and blockers
- `listing_drafts`: unpublished AI-generated listing drafts
- `builds`: recent internal build records
- `orders`: recent product orders, excluding buyer credentials
- `revenue_events`: gross, net and agent-credit states
- `controls`: read-only and non-publication guarantees
