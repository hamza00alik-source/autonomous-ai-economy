# AAE crypto checkout provider decision (2026-11-18)

## Decision

Do not enable the current NOWPayments-only storefront as a worldwide checkout. The current integration is technically useful, but provider terms exclude US, UK and EU residents/citizens. A single NOWPayments integration therefore conflicts with AAE's worldwide-buyer requirement.

No provider reviewed in this pass is approved for production. Keep public checkout and outbound transfers disabled.

## Provider comparison

| Provider | Useful capabilities | Material blocker / caveat | Decision |
|---|---|---|---|
| NOWPayments | Existing Worker integration; hosted invoice; signed HMAC-SHA512 IPN; USDT/USDC options; 1% standard service fee stated by provider | Current terms say services are not rendered to EU, UK and US residents/citizens; provider can also restrict markets. | Do not use as sole worldwide provider. Keep adapter dormant as a possible jurisdiction-limited route only after legal review. |
| Cryptomus | Hosted merchant API and payment notifications | Its terms exclude US persons; its published AML prohibited-country list includes Pakistan. | Reject for this merchant. |
| CoinPayments (new platform) | REST API; hosted invoices; signed/retried webhooks; regional merchant instances; KYC onboarding | Current FAQ says it is not serving EU/EEA clients since 2026-07-01; compliance list includes US and other restricted jurisdictions. Pakistan instance eligibility needs explicit confirmation. | Not a worldwide single-provider fit; do not integrate until Pakistan instance and target-country coverage are confirmed. |
| CPAY | Advertises non-custodial wallet settlement, Base, USDT/USDC, API and signed webhooks | Its terms say it may act as agent to receive, hold and disburse funds, which conflicts with the non-custodial marketing claim. Merchant jurisdiction/contracting entity and actual custody model need written confirmation. | Hold; do not entrust funds or integrate based on marketing claims. |
| Plisio | Invoice API and signed callback verification; broad crypto support; claims 0.5% API fee | Its service appears custodial/balance-based in independent review; no reliable official evidence found here proving Pakistan merchant eligibility and worldwide buyer access. | Hold pending written eligibility, custody and settlement confirmation. |
| DepiPay | Wallet-connected non-custodial design; per-invoice addresses; EVM-style signed requests; event polling; legal restricted list does not list Pakistan, US, UK or EU | Current developer/FAQ docs conflict on authentication; current supported network list is Ethereum, BSC and TRON (Solana described as coming soon), not Base. Existing AAE public Base address is not enough to authorize a new smart-wallet setup or sign API requests. | Best candidate for a non-custodial pilot only after its API/auth, wallet ownership, supported chain and buyer-jurisdiction terms are independently confirmed. No keys or funds supplied. |

## Evidence links

- NOWPayments terms: https://nowpayments.io/doc/fd-tos.pdf?v=1.3
- NOWPayments IPN signature setup: https://nowpayments.zendesk.com/hc/en-us/articles/21395546303389-IPN-and-how-to-setup
- NOWPayments supported assets: https://nowpayments.io/supported-coins
- Cryptomus terms: https://cryptomus.com/tos
- Cryptomus AML prohibited-country list: https://storage.cryptomus.com/docs/aml.pdf
- CoinPayments compliance: https://www.coinpayments.net/compliance
- CoinPayments FAQ (EU/EEA service change): https://www.coinpayments.net/faq
- CoinPayments regional instances: https://docs.coinpayments.net/instances/
- CoinPayments onboarding/KYC: https://docs.coinpayments.net/api/getting-started/
- CPAY terms: https://docs.cpay.world/policies-and-compliance/terms-of-service/
- CPAY API checkout: https://docs.cpay.world/for-developers/api/using-api-for-checkout/
- Plisio invoice API and callback verification: https://plisio.net/documentation/endpoints/create-an-invoice
- DepiPay legal restrictions: https://depipay.com/legal.html
- DepiPay FAQ: https://depipay.com/faq.html
- DepiPay API: https://depipay.com/docs.html

## AAE implementation rules

1. Keep NOWPayments routes, current webhook verifier and D1 invoice tables behind existing flags. Do not weaken authorization.
2. Do not treat a provider's marketing statement ("global", "no KYC", "non-custodial") as proof of merchant eligibility, buyer coverage, custody, or legal compliance.
3. Before implementing a new provider, require official documentation for:
   - Pakistan-based merchant eligibility and actual contracting entity;
   - supported buyer countries, including US, UK, EU/EEA and other intended markets;
   - USDT/USDC token contract and network identifiers;
   - hosted invoice creation and expiry;
   - signed webhook verification, retry policy, terminal paid state and over/underpayment behavior;
   - wallet settlement/custody model, fees, withdrawal and refund mechanics;
   - key ownership and recovery.
4. The payment adapter must map provider-specific events into a common internal state machine. Only independently verified full payment may unlock the download. Duplicate/out-of-order notifications must be idempotent.
5. Do not add a payout signer or store the owner's wallet private key in Worker secrets. A wallet signature, smart-wallet creation or key delegation is a separate security-sensitive setup and must be explicitly authorized.
6. Do not activate public checkout, run a live payment, publish a product, move funds, or deploy production code without separate owner approval.
7. Do not report revenue until the on-chain receipt or provider settlement is verified and reconciled against fees/refunds.

## Current readiness

- Existing NOWPayments invoice/IPN/store-download code: present on main.
- Provider API credentials and IPN secret: not verified as configured.
- Public checkout: must remain disabled.
- Production test payment: not performed.
- Product publication: not performed.
- Verified sales/revenue: zero.
- Next engineering step: implement a provider-neutral payment state interface and automated tests, then add a provider only after the above eligibility and custody gates pass.
