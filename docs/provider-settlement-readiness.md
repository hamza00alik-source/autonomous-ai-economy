# Provider settlement and agent-budget funding readiness

## Current decision

No provider is approved for production revenue-to-ledger funding. Do not enable automatic budget crediting, live checkout, or outbound transfers yet.

## Plisio: conditional technical candidate only

The public Plisio API documentation describes:
- Invoice callbacks with a `verify_hash` signature field.
- Invoice states including `pending`, `pending internal`, and `completed`; the documentation describes `completed` as paid in full.
- Transaction lookup through the operations endpoint, including status and transaction/wallet references such as `tx_url` and `wallet_hash`.

Sources:
- https://plisio.net/documentation/endpoints/create-an-invoice
- https://plisio.net/documentation/endpoints/transaction-details
- https://plisio.net/documentation/endpoints/transactions
- https://plisio.net/docs/plisio-terms-of-use.pdf
- https://plisio.net/docs/aml.pdf
- https://plisio.net/woocommerce-accept-crypto
- https://plisio.net/accept-usdt

Plisio's marketing pages for several hosted-store plugins advertise worldwide availability, direct-to-merchant-wallet payments and no KYC at plugin setup (for example https://plisio.net/woocommerce-accept-crypto and https://plisio.net/accept-usdt). Treat those as product-specific marketing claims, not a binding eligibility determination for this AAE API integration. Plisio's AML policy states that risk-based KYC may be required for flagged transactions/accounts, and its Terms require compliance with local law and reserve suspension rights.

This is enough to design an adapter, not enough to approve the provider. The public terms do not explicitly confirm that a Pakistan-resident merchant can use the exact API/merchant setup proposed for AAE. Obtain written Plisio confirmation of:
1. Pakistan-resident individual / Pakistan business onboarding eligibility and exact KYC documents.
2. Whether a non-custodial merchant accepting payment for its own digital downloads is supported under their merchant terms.
3. Supported payout currencies and chains for the merchant account, and whether funds are forwarded to a merchant-controlled wallet or held in a Plisio wallet.
4. What `completed` means for merchant settlement, whether it guarantees payout to the configured wallet, and how to retrieve the payout transaction hash and fee.
5. Fees, limits, refund/chargeback handling, and any country or asset restrictions applicable to the specific account.

No Plisio account has been created and no API key has been issued or configured.

## Pakistan regulatory gate

The Virtual Assets Act, 2026 applies to virtual asset service providers carrying on or holding themselves out as providing a virtual asset service in or from Pakistan. Its licensing categories include custody and virtual-asset transfer/settlement services. The PVARA licensing framework states that a person may not carry on a virtual asset service in or from Pakistan by way of business without the relevant license.

Official references:
- https://pvara.gov.pk/regulations
- https://pvara.gov.pk/licensing
- https://pvara.gov.pk/documents/Virtual%20assets%20Act%202026%20passed%20by%20NA.pdf
- https://pvara.gov.pk/advisories/virtual-asset-announcements-and-activities

Whether AAE merely receiving payment for its own digital products, or any proposed treasury/agent transfers and custody model, falls within a regulated service requires qualified Pakistan legal advice or written PVARA clarification. A third-party payment processor's license does not automatically authorize AAE to provide separate virtual-asset services.

## Ledger and allocation gates

The current cloud ledger supports three-letter uppercase currency codes such as `USD`. It cannot accurately represent four-letter token assets such as `USDC` or `USDT`. Do not store a token amount as USD or treat a USD-denominated invoice value as an on-chain token balance.

Before crediting any agent budget, all of the following must be implemented and verified:
1. Provider-specific callback signature verification and provider API transaction lookup.
2. Final invoice status, exact order binding, received amount, fee, refund/reversal state and provider payout settlement evidence.
3. The actual asset and chain, merchant-controlled destination address, transaction hash, and required chain finality.
4. An asset-aware ledger model that distinguishes currency, token contract, network/chain and integer token precision.
5. A separate owner-signed allocation policy defining agent, treasury, reserve and owner shares. No split percentages are assumed.
6. One atomic journal transaction and allocation from the verified receipt, with idempotent provider references and compensating reversals.

The existing `agent_revenue_events` rows remain pending reconciliation. They are attribution records, not cleared funds. The new cloud financial accounts created by owner enrollment start at zero. The provider integration must not promote pending events to revenue merely because a buyer's invoice callback arrived.

## Safe implementation boundary

The cloud financial scheduler, spending controls and owner emergency pause remain simulated-only. No provider settlement is imported into the cloud ledger, no agent account is funded, and no wallet transfer is initiated until the above gates are satisfied and the owner separately approves any production activation.
