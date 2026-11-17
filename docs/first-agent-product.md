# First digital product pilot

Status: **product source and reproducible bundle implemented; demand and sales unverified.**

## Product

The first product artifact is **Store Catalog Cleaner**, a standalone browser utility for small online-store operators who need to inspect and clean CSV product/inventory catalogs before importing them into another system.

It supports local CSV parsing, duplicate and blank-row checks, missing-value summaries, generic header normalization, optional duplicate-key removal, preview and CSV export. It has no remote scripts, analytics, accounts, uploads or API dependency.

Source: products/store-catalog-cleaner/

Build a reproducible ZIP with a root-level index.html:

```bash
pip install -e ".[dev]"
economy-product build --output dist/store-catalog-cleaner.zip
pytest
```

The ZIP contains the browser app, README, listing copy and SHA-256 manifest. The build command does not publish or upload it.

## Why this is the first pilot

- The deliverable is software, not an AI-written instruction manual.
- It can run offline in a modern browser and does not need paid APIs or a hosted database.
- The product can be mechanically packaged and integrity-checked.
- It is a narrow utility with a clear buyer task: cleaning CSV catalog data before import.

This is a testable product hypothesis, **not verified market demand**. Generic CSV tools are widely available; do not claim a unique market gap or willingness to pay without independent evidence and actual customer tests.

## Candidate storefront: Gumroad

Gumroad documents a browser-app upload format: ZIP file with index.html at the top level. Its help article describes uploading the ZIP as a web app. Gumroad also currently lists Pakistan among supported local-bank payout countries. Verify the actual seller account's payout settings and identity checks before relying on this route.

Important restrictions and gaps:

- Gumroad's terms require truthful seller registration and place responsibility for account activity on the registered user/entity; they prohibit sharing account/password credentials and false identity.
- The Gumroad AI connector can draft products, read sales and payouts, and publish with product access. Its help page says a new draft has no files: the product files must still be added in Gumroad.
- The connector must be separately connected and authorized; no access token or account credentials are stored in this repository.
- The current repository does not have a Gumroad connector or verified seller account.
- No listing is created, uploaded or published by this build.
- Do not automate browser login, share passwords, misrepresent an AI agent as a human, or bypass seller verification.

## First-sale measurement

Only count revenue after a real external buyer pays, receives the product, the payment provider confirms settlement, and net proceeds after fees/refunds are reconciled. A draft, listing, click, download, pending balance, simulated ledger entry or test order is not revenue.

Track: impressions, product-page visits, conversion, refunds, support burden, platform fees, payout status and net amount. If there is no buyer traffic or conversion, change the product based on evidence rather than multiplying unvalidated products.

## Remaining blockers

1. Verify the product solves a real recurring problem and has a reason to be purchased instead of free alternatives.
2. Confirm Gumroad seller eligibility and local-bank payout setup for the true account holder.
3. Connect an approved Gumroad integration with least-privilege permissions, if available.
4. Add the ZIP to a Gumroad product draft and confirm platform terms permit the intended disclosed AI-assisted workflow.
5. Obtain explicit publication authority before the first live listing.
6. Verify actual buyer payments and cleared payouts.

The economy cannot be called always-on or revenue-generating until the production runtime, buyer channel, seller identity, payment settlement and customer support loops are live and tested.
