# Base USDC Worker integration

## Current implementation

The private Worker contains a gated Base-native USDC checkout API, signed-invoice creation, buyer order-status and protected-download endpoints, and a scheduled Base event indexer. The public storefront source now uses the Base invoice API and a locally bundled viem wallet client; it no longer routes new purchases through NOWPayments.

The wallet page requests the buyer's explicit approval for exactly the invoice amount, then calls the signed-invoice checkout contract. Before asking for approval, it verifies deployed bytecode and reads the contract's immutable merchant, invoice signer and native USDC token getters against the server-signed invoice. It checks the buyer's Base USDC balance and waits for approval confirmation before submitting payment. It never requests unlimited allowance. Wallet rejection, insufficient balance, chain switching, approval failure, and payment submission are surfaced to the buyer.

The frontend bundle is built locally from the pinned npm dependency tree using esbuild:
`npm --prefix cloudflare/worker run build:wallet`.
The generated `public/wallet-checkout.js` is a build artifact and should not be hand-edited. CI builds it before Worker dry-run validation.

## Invoice and settlement lifecycle

1. The Worker creates a fixed-price server-side order; the browser cannot submit a product ID or price.
2. It generates an unpredictable order ID and a random buyer download credential; only the credential hash is stored server-side.
3. A dedicated invoice-only signer signs the EIP-712 invoice for exact order ID, exact USDC base-unit amount, deadline, chain and contract domain, and immutable merchant.
4. The invoice row is inserted idempotently before the signed invoice and buyer token are returned.
5. The buyer wallet switches to Base (8453), checks native Base USDC balance, approves only the exact amount, then calls `pay(bytes32,uint256,uint256,bytes)`.
6. Browser redirects, wallet transaction submission, and buyer-supplied transaction hashes are never proof of payment.
7. The Worker indexer validates chain, contract emitter, event signature, native USDC token, merchant, exact amount, order ID, successful receipt, canonical block and confirmation threshold.
8. Only a validated event may atomically mark the invoice settled, persist the unique chain/transaction/log event, create revenue attribution, and set the seven-day download entitlement.
9. The storefront polls the authenticated order endpoint and reveals the download only after the Worker reports active settled entitlement.

## Reorg, duplicates and mismatches

- The event primary key is (chain_id, transaction_hash, log_index).
- The indexer cursor stores the next block and last observed block hash.
- A detected reorg rewinds a bounded recent window, marks affected events orphaned, moves affected invoices to review, revokes download access and moves revenue to refund review.
- Current bounded rewind is not a complete deep-reorg proof. A reorg deeper than the configured lookback may require manual review and reconciliation; this remains a production blocker until a conservative ancestor/checkpoint strategy and operational alerting are implemented.
- Unknown orders, expired invoices, wrong token, wrong merchant, amount mismatch, wrong emitter, failed receipt, duplicate order payment, or malformed logs are quarantined. They never unlock a download.

## Security and production blockers

- Public checkout, indexer, legal-review and crypto-enablement gates remain disabled unless separately configured and approved.
- No deployed contract address, live Base RPC, production invoice signer, or real transaction has been verified in this task.
- The dedicated invoice signer key is security-critical and must not be the merchant wallet key. It has not been provisioned.
- The contract requires independent review and deployment approval. Do not deploy, sign, enable checkout or transfer funds without explicit authorization.
- Pakistan legal classification of this merchant payment flow remains unresolved. Obtain qualified Pakistan legal advice or written PVARA clarification before activating real crypto checkout.
- A mocked CI test is not a live wallet or chain rehearsal. No sale, customer payment, settled revenue, or production readiness is claimed.
