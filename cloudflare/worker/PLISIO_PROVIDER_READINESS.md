# Plisio provider readiness — disabled evaluation

## Decision

Plisio is a **conditional technical candidate only** for Autonomous AI Economy (AAE). AAE is still under development and is not yet a functioning sales or payment system. This document does not approve live checkout, payment collection, wallet movement, or production deployment.

The existing NOWPayments and Base USDC work is not replaced by this evaluation. AAE remains a separate project from OpenCompany.

## What the official material establishes

- Plisio's API requires a registered account and a site/API configuration to obtain a secret key. API requests use HTTP GET and return JSON. The key is supplied as an `api_key` query parameter. See [API introduction](https://plisio.net/documentation/getting-started/introduction).
- Invoice creation is documented at `GET https://api.plisio.net/api/v1/invoices/new`. Required fields include a unique `order_number` and `order_name`; USD-denominated pricing can use `source_currency=USD` and `source_amount`. An invoice response contains a Plisio transaction ID and hosted invoice URL. See [Create an invoice](https://plisio.net/documentation/endpoints/create-an-invoice).
- The callback documentation identifies `completed` as the fully paid status and also lists pending, expired, error and cancelled states. For non-PHP integrations, Plisio explicitly requires `json=true` on the callback URL. Its Node example removes `verify_hash`, preserves the remaining object's received property order, serializes with `JSON.stringify`, and verifies HMAC-SHA1 using the API secret. The PHP/form example is a separate format using sorted PHP-serialized fields; it must not be mixed with the JSON verifier. See [Create an invoice — callback verification](https://plisio.net/documentation/endpoints/create-an-invoice).
- Plisio's AML/KYC document says automated risk controls can hold transactions and request identity verification through SumSub. It reserves the right to apply KYC/AML to customers, wallet addresses and selected assets. Therefore, **no-KYC is not guaranteed**. See [Plisio AML/KYC policy](https://plisio.net/docs/aml.pdf).
- The currently linked Plisio Terms of Use describe service wallets and storage/exchange/management functions, reserve broad account-suspension rights, and say account-held crypto may need support-assisted withdrawal if an account is suspended. The published PDF is dated 12 March 2019, so it is not sufficient evidence of current API custody/settlement terms. Obtain current API terms and written clarification rather than relying on this older general terms document. See [Terms of Use PDF](https://plisio.net/docs/plisio-terms-of-use.pdf).
- A Plisio WHMCS marketing page claims direct wallet payments and no KYC for that plugin, but those claims do not prove that the general API account, AAE's intended flow, or a Pakistan-based project qualifies on the same terms. Do not rely on plugin marketing as a legal or contractual assurance.

## Required gates before any live integration

1. **Pakistan legal classification:** Obtain qualified Pakistan counsel's written analysis or PVARA clarification for the intended flow: a Pakistan-based project offering its own digital downloads, using a third-party processor, and receiving crypto to a project-controlled wallet. Confirm whether the project or any part of the payment flow is providing a regulated Virtual Asset Service, and what authorization is required. Do not assume an exemption.
2. **Written Plisio eligibility:** Ask Plisio support to confirm in writing whether a person or organization resident/operating in Pakistan may open and use an API account for this intended digital-download flow, which countries are excluded, what identity or organization checks are required at onboarding and at what thresholds, and whether a transaction can be held pending manual identity review.
3. **Settlement/custody terms:** Obtain written confirmation of the settlement path for the actual API invoice product: whether funds go directly to a project-controlled wallet, whether Plisio or an intermediary can hold/convert funds, supported chains/assets, minimums, fees, refund mechanics, and who bears network fees. The WHMCS page's direct-payment claim is not enough to establish API settlement terms.
4. **Callback contract:** For the JSON path, set `json=true` and verify the parsed payload using the documented Node algorithm without sorting keys. Preserve the exact property order produced by JSON parsing, remove only `verify_hash`, serialize with `JSON.stringify`, and compare the HMAC-SHA1 digest in constant time. The PHP/form callback format is a separate algorithm and is not accepted by this JSON verifier.
5. **Payment verification:** Only a verified callback plus a provider-side invoice/transaction lookup that confirms matching order number, USD source amount, crypto received amount, asset, and final completed state may mark an order paid. Pending, expired, cancelled, error, underpayment, mismatched amount, unknown status, or unverifiable callbacks must never unlock downloads.
6. **Operational controls:** Keep provider credentials separate from existing provider secrets and store them only as Worker secrets. Never log API keys or full provider URLs. Use idempotent order reservations, duplicate callback protection, rate limits, server-controlled prices, download-token hashing, and a seven-day entitlement. Keep checkout and payouts disabled until separately approved.

## Proposed isolated implementation (not yet wired)

- Add a provider module with explicit `AAE_PLISIO_ENABLED` defaulting to false.
- Add a separate route such as `POST /v1/store/plisio/checkout` and callback route `POST /v1/payments/plisio/callback`; do not reuse or overwrite the Base USDC route.
- Add a provider discriminator and separate invoice/event ledger records (or a reviewed migration) so Plisio callbacks cannot collide with existing invoice IDs or event hashes.
- Create invoices using server-owned product/price data only; return only a validated HTTPS `plisio.net` invoice URL.
- Use the isolated JSON verifier in `src/plisio.js` only for callbacks sent with `json=true`; enforce exact order and amount matching; query Plisio for final transaction state before settlement; deliver only after final verification.
- Isolated verifier tests cover valid signatures, tampering, wrong keys, malformed payloads, and property-order sensitivity. The end-to-end payment adapter still needs tests for duplicate/out-of-order callbacks, wrong order, wrong amount/currency, underpayment, expired invoice, unknown statuses, replay, and provider API uncertainty.
- Keep this module dormant unless all legal, eligibility, settlement, security and owner-approval gates are satisfied.

## Current state

- AAE is not yet a functioning sales or payment system.
- No Plisio account was created.
- No identity verification was attempted.
- No Plisio API key or callback secret was requested or stored.
- No Plisio adapter has been connected to a live route.
- No live checkout, customer payment, wallet transfer, product delivery or revenue has occurred.
- No production Worker, D1 database, storefront or existing provider route was changed by this evaluation.

## Official references

- [Plisio API introduction](https://plisio.net/documentation/getting-started/introduction)
- [Plisio invoice creation and callback documentation](https://plisio.net/documentation/endpoints/create-an-invoice)
- [Plisio AML/KYC explanation](https://plisio.net/docs/aml.pdf)
- [Plisio WHMCS plugin marketing page](https://plisio.net/whmcs-accept-crypto) — marketing claims only; not proof of general API eligibility or Pakistan legal compliance.
- [Plisio Terms of Use PDF](https://plisio.net/docs/plisio-terms-of-use.pdf) — linked document is dated 12 March 2019; obtain current API terms before relying on it.
- [PVARA licensing](https://pvara.gov.pk/licensing)
- [PVARA regulations](https://pvara.gov.pk/regulations)
