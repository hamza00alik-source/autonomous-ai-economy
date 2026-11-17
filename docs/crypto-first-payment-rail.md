# Crypto-first payment rail

Status: **NOWPayments invoice/IPN adapter implemented in the private Cloudflare Worker; not deployed, not connected to a seller account, and not enabled for live money.**

## User requirement

Prioritize crypto and other online payment methods that can receive money without a person manually checking each transaction. The system should automatically verify provider-signed payment notifications, reconcile the amount and order, and unlock delivery only after full settlement.

This is not a request to evade KYC, sanctions screening, provider rules or local law. Account onboarding and transaction review may still require human identity checks. A cryptographic agent identity is not a legal identity.

## Candidate rails

### 1. NOWPayments — first hosted-checkout candidate

The current adapter uses the hosted invoice API and Instant Payment Notifications (IPN).

- The provider says crypto-only merchants generally do not need KYB/KYC at onboarding; it may request identity and source-of-funds checks in the rare case that a transaction is flagged as suspicious.
- Fiat options, including fiat charging or fiat cash-out, require KYB/KYC.
- The provider says it is non-custodial for its standard payment flow: the customer pays a provider deposit address, then funds are automatically forwarded to the merchant's configured payout wallet. It says it does not store merchant funds or hold the merchant's private keys. If exchange is required, the provider processes the conversion before forwarding; avoid enabling its separate custody-balance product.
- Its published processing fee is 0.5% for payments without exchange and 1% for multi-currency, fixed-rate or fee-paid-by-user payments; blockchain network fees are additional.
- The provider says it operates globally except where prohibited by applicable law and reserves the right to restrict territories where local licensing requirements prevent service. Pakistan eligibility must be confirmed before activation.
- Outbound payout APIs are not implemented in this project; incoming payments are the only scope of this adapter.

Official references:
- https://nowpayments.io/help/security/kyc-aml/kyc-aml-procedure
- https://nowpayments.io/help/about-nowpayments/about/where-are-my-funds-stored
- https://nowpayments.io/help/about-nowpayments/about
- https://nowpayments.zendesk.com/hc/en-us/articles/21395546303389-IPN-and-how-to-setup
- https://nowpayments.zendesk.com/hc/en-us/articles/18395434917149-Payment-statuses
- https://documenter.getpostman.com/view/7907941/2s93JusNJt

### 2. BTCPay Server — self-custodial Bitcoin alternative

BTCPay is open-source and non-custodial. It can accept Bitcoin and Lightning directly to a merchant-controlled wallet without a payment processor taking custody. It does not require merchant KYC, but it requires a server or a trusted third-party host. A self-hosted Bitcoin/Lightning node has meaningful storage and maintenance requirements; this is not the zero-cost default. Native support is Bitcoin/Lightning; altcoins require separate integrations.

Official references:
- https://docs.btcpayserver.org/FAQ/Deployment/
- https://docs.btcpayserver.org/btcpay-basics/btcpayvsothers/
- https://docs.btcpayserver.org/FAQ/General/
- https://docs.btcpayserver.org/API/Greenfield/v1/

## Pakistan legal boundary

The Virtual Assets Act, 2026 came into force on 5 March 2026. It applies to Virtual Asset Service Providers operating in or from Pakistan and requires licensing for listed Virtual Asset Services. Schedule I includes broker-dealer, custody, exchange, and transfer/settlement services. The Act's broker-dealer schedule includes an own-account exemption where a person deals solely on its own account, does not execute orders for customers, and does not hold or control customer assets. That wording is not a blanket legal opinion for this project or every crypto payment arrangement.

PVARA's official site says the Pakistan Virtual Asset Services Regulations, 2026 and Activity-Specific Regulations, 2026 were notified on 21 August 2026. Before enabling a crypto checkout from Pakistan, verify the exact merchant activity, provider eligibility, foreign-exchange/tax treatment and any licensing implications with qualified local counsel or PVARA. Do not provide exchange, custody, escrow, or transfer services to third parties unless separately authorized.

Official references:
- https://www.pvara.gov.pk/regulations
- https://pvara.gov.pk/licensing
- https://www.sbp.org.pk/circulars/bprd-circular-letter-no-10
- https://staging.na.gov.pk/uploads/documents/69aae92ebf61c_955.pdf

## Other online payout rails

Crypto is the first automated receipt rail, not the only permitted rail. A second class of methods is platform-native payout to an already verified online account (for example, Payoneer where a chosen marketplace supports it). That can avoid a human checking every individual payout, although account-level verification and provider controls may still apply. This repository does not yet connect to Payoneer or any other fiat payout API; add such an adapter only after selecting a specific marketplace/provider and confirming its country, payout, API and compliance terms.

## Secondary online marketplace payout route

For customers who buy through a 3D-asset marketplace, the marketplace can collect the sale and pay the creator to an online payout account. This is separate from direct crypto checkout and can run on scheduled payouts without a person manually confirming every sale. Account-level onboarding, tax forms, identity checks or risk reviews may still apply.

| Marketplace | Online payout route | Automation/verification caveat |
|---|---|---|
| TurboSquid | Payoneer, PayPal or Skrill | Its current help page says balances are paid monthly and the first payout is subject to a one-time 90-day wait from the first sale. It requires complete artist/payment information; the public help page does not promise that identity review will never be requested. |
| CGTrader | Hyperwallet destination, with Payoneer available depending on location | Its current seller payout schedule explicitly requires completion of KYC and a verified payment agreement. Earnings become payable 20 days after the sale and are processed weekly. |
| itch.io | PayPal/Payoneer in its collected-payout system | Not a fit for the no-manual-review goal: it requires a tax interview, a $5 minimum, a 7-day waiting period, fraud review and staff approval before payout. |

Sources:
- TurboSquid: https://www.turbosquid.com/help/en/articles/9937539-how-do-i-get-paid-what-do-i-need-to-do
- CGTrader payout schedule: https://www.cgtrader.com/pages/earnings-and-payout-schedule
- CGTrader payout methods: https://help.cgtrader.com/hc/en-us/articles/360015145137-Payout-methods
- itch.io payout requirements: https://itch.io/docs/creators/payments

Practical choice: keep direct crypto checkout as the primary rail; investigate TurboSquid as a 3D-asset marketplace route to Payoneer, subject to account eligibility and its 90-day first-payment delay. CGTrader is a backup if its one-time KYC and Payoneer availability are acceptable. Exclude itch.io collected payouts where staff approval conflicts with the automation requirement. This repository does not yet automate listings or marketplace payout APIs.

## Implemented private Worker API and customer delivery

The source now includes a small, fixed-price customer storefront for the first asset pack. The public product page and checkout are both hidden unless the owner configures the payment provider, completes the eligibility/legal checks, and explicitly enables both feature flags. A Worker deployment with flags false does not publish the product page.

- `GET /` — serves the customer product page from Workers Static Assets.
- `POST /v1/store/checkout` — public, same-origin, rate-limited checkout for the single fixed product at **US$5.00**. Customers cannot submit a custom price or product ID. It creates a random order ID and 256-bit buyer access token; only the token's SHA-256 hash is stored.
- `POST /v1/payments/nowpayments/ipn` — public provider callback. Verifies `x-nowpayments-sig` with HMAC-SHA-512 over recursively key-sorted JSON before touching payment state.
- `GET /v1/store/orders/{order_id}` — buyer-token authenticated order status. The browser polls this after the provider redirects back.
- `GET /v1/store/orders/{order_id}/download` — buyer-token authenticated download. It streams the ZIP from the Worker Static Assets binding only after a matching, full, provider-confirmed payment reaches `settled`. Download access expires after seven days; repeat downloads are allowed during that window.
- `GET /v1/agents/{agent_id}/revenue` — owner-token authenticated agent revenue report. See [agent revenue attribution](agent-revenue-accounting.md).
- `GET /v1/payments/{order_id}` and `POST /v1/payments/nowpayments/invoices` — owner-token authenticated operational endpoints.

The deploy workflow rebuilds the ZIP and includes it as a Worker static asset. The Worker runs before static assets and blocks direct requests to `/downloads/*`; the file is served only through the authenticated download route. No separate R2 bucket is needed for this single small product.

Only a valid, matching callback with `payment_status=finished`, the expected invoice/order/price/currency, and the full required crypto amount can become `settled`. Partial payments remain `underpaid`; unknown/mismatched events are quarantined. Duplicate callbacks are idempotent. Lower-status late callbacks cannot downgrade a settled order, and a refund changes the order to `refunded`, disabling downloads.

The buyer access token is returned once at checkout and stored in that browser's local storage. The customer must return in the same browser/device to retrieve the download; a lost token currently has no self-service recovery flow. The Worker stores only minimal payment metadata and event hashes; it does not retain raw webhook bodies, buyer identity, wallet private keys, or seed phrases. A settled sale is attributed to the internal `game-asset-builder` producer ID in an idempotent revenue table. Gross receipts remain pending wallet/fee/refund reconciliation; net proceeds and agent credits are not recorded as earned/disbursed until reconciled. It does not issue refunds, exchange assets, or create outbound transfers.

## Enablement prerequisites

1. Confirm NOWPayments accepts the actual merchant and activity from Pakistan, and complete any provider-required onboarding honestly.
2. Obtain qualified local advice on the Virtual Assets Act, 2026 and related tax/foreign-exchange obligations for the precise setup.
3. Only after the first two checks, add Cloudflare secrets `NOWPAYMENTS_API_KEY` and `NOWPAYMENTS_IPN_SECRET`, then set GitHub Actions variable `AAE_CRYPTO_ENABLEMENT_APPROVED=true`. Keep `AAE_PUBLIC_CHECKOUT_ENABLED` unset/false until the product QA and test-invoice checks are complete; set it to `true` only when you intentionally want the customer store to accept live orders. The deployment workflow refuses public checkout unless both flags and both provider secrets are present.
4. Deploy the Cloudflare Worker and D1 migration using the manual deployment workflow.
5. Create one low-value test invoice and verify valid, invalid, duplicate, delayed, partial, expired and mismatched IPNs before any public listing.
6. Deploy and run a low-value end-to-end test: create invoice, confirm provider IPN, poll buyer order status, download the asset, test refund lockout, and reconcile actual wallet receipt and fees. Do not open public checkout until the test passes.

Never paste provider credentials, private keys or seed phrases into chat or source control. No account has been created, no secret has been configured, no transaction has been made, and no revenue is claimed.
