# Plisio provider readiness — disabled evaluation

## Decision

Plisio is a **conditional technical candidate only** for Autonomous AI Economy (AAE). This document does not approve merchant onboarding, live checkout, payment collection, wallet movement, or production deployment.

The existing NOWPayments and Base USDC paths are not replaced by this evaluation. AAE remains a separate project from OpenCompany.

## What the official material establishes

- Plisio's API requires a registered account and a site/API configuration to obtain a secret key. API requests use HTTP GET and return JSON. The key is supplied as an `api_key` query parameter. See [API introduction](https://plisio.net/documentation/getting-started/introduction).
- Invoice creation is documented at `GET https://api.plisio.net/api/v1/invoices/new`. Required fields include a unique `order_number` and `order_name`; USD-denominated pricing can use `source_currency=USD` and `source_amount`. An invoice response contains a Plisio transaction ID and hosted invoice URL. See [Create an invoice](https://plisio.net/documentation/endpoints/create-an-invoice).
- The callback documentation identifies `completed` as the fully paid status. It also lists pending, expired, error and cancelled states. The callback includes `verify_hash`; the documented PHP example computes HMAC-SHA1 over PHP-serialized, sorted callback fields. The Node example instead JSON-stringifies the sorted object and explicitly requires `json=true` in the callback URL. This serialization difference must be resolved with the official SDK or written provider confirmation before implementing a production verifier.
- Plisio's AML/KYC document says automated risk controls can hold transactions and request identity verification through SumSub. It reserves the right to apply KYC/AML to customers, wallet addresses and selected assets. Therefore, **no-KYC is not guaranteed**. See [Plisio AML/KYC policy](https://plisio.net/docs/aml.pdf).
- A Plisio WHMCS marketing page claims direct wallet payments and no KYC for that plugin, but those claims do not prove that the general API account, AAE's specific merchant flow, or a Pakistan-based merchant qualifies on the same terms. Do not rely on plugin marketing as a legal or contractual assurance.

## Required gates before any live integration

1. **Pakistan legal classification:** Obtain qualified Pakistan counsel's written analysis or PVARA clarification for this exact flow: a Pakistan-based seller accepting crypto for its own digital downloads, using a third-party processor, and receiving crypto to its own wallet. Confirm whether the seller or any part of the payment flow is providing a regulated Virtual Asset Service, and what authorization is required. PVARA's current licensing/regulatory material describes licensing for covered VASP activities; do not assume an own-goods merchant exemption.
2. **Written Plisio eligibility:** Ask Plisio support to confirm in writing that an individual or business resident/operating in Pakistan may open and use a merchant API account for this exact digital-goods business, which countries are excluded, what KYC/KYB is required at onboarding and at what thresholds, and whether a transaction can be held pending manual identity review.
3. **Settlement/custody terms:** Obtain written confirmation of the settlement path for the actual API invoice product: whether funds go directly to the merchant-controlled wallet, whether Plisio or an intermediary can hold/convert funds, supported chains/assets, minimums, fees, refund mechanics, and who bears network fees. The WHMCS page's direct-payment claim is not enough to establish API settlement terms.
4. **Callback contract:** Resolve the Node callback signature canonicalization ambiguity. Confirm whether the exact callback is JSON or form encoded, canonical sorting/serialization, treatment of nested/array fields, and whether `verify_hash` is HMAC-SHA1 over the exact byte sequence shown in the SDK. Obtain fixed official test vectors.
5. **Payment verification:** Only a verified callback plus a provider-side invoice/transaction lookup that confirms matching order number, USD source amount, crypto received amount, asset, and final completed state may settle an order. `pending`, `pending internal`, `expired`, `cancelled`, `error`, underpayment, mismatched amount, unknown status, or unverifiable callbacks must never unlock downloads. Reconcile actual wallet receipt before revenue is called realized.
6. **Operational controls:** Separate provider credentials from NOWPayments secrets; store them only as Worker secrets. Never log API keys or full provider URLs. Use idempotent order reservations, duplicate callback protection, rate limits, amount/product pricing controlled server-side, download-token hashing, and a seven-day entitlement. Keep public checkout and payouts disabled until separately approved.

## Proposed isolated implementation (not yet wired)

- Add a provider module with explicit `AAE_PLISIO_ENABLED` defaulting to false.
- Add a separate route such as `POST /v1/store/plisio/checkout` and callback route `POST /v1/payments/plisio/callback`; do not reuse or overwrite the Base USDC route.
- Add a provider discriminator and separate invoice/event ledger records (or a reviewed migration) so Plisio callbacks cannot collide with NOWPayments invoice IDs or event hashes.
- Create invoices using server-owned product/price data only; return only a validated HTTPS `plisio.net` invoice URL.
- Verify callbacks using the provider-confirmed canonicalization; enforce exact order and amount matching; query Plisio for final transaction state before settlement; deliver only after final verification.
- Add tests for signature tampering, wrong key, duplicate/out-of-order callbacks, wrong order, wrong amount/currency, underpayment, expired invoice, unknown statuses, replay, and provider API uncertainty.
- Keep this module dormant unless all legal, eligibility, settlement, security and owner-approval gates are satisfied.

## Current state

- No Plisio account was created.
- No merchant verification was attempted.
- No Plisio API key or callback secret was requested or stored.
- No Plisio adapter has been connected to a live route.
- No live checkout, customer payment, wallet transfer, product delivery or revenue has occurred.
- No production Worker, D1 database, storefront or existing provider route was changed by this evaluation.

## Official references

- [Plisio API introduction](https://plisio.net/documentation/getting-started/introduction)
- [Plisio invoice creation and callback documentation](https://plisio.net/documentation/endpoints/create-an-invoice)
- [Plisio AML/KYC explanation](https://plisio.net/docs/aml.pdf)
- [Plisio WHMCS plugin marketing page](https://plisio.net/whmcs-accept-crypto) — marketing claims only; not proof of general API eligibility or Pakistan legal compliance.
- [PVARA licensing](https://pvara.gov.pk/licensing)
- [PVARA regulations](https://pvara.gov.pk/regulations)
