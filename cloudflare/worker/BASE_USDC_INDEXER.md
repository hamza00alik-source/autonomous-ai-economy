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
- Any mismatch between the stored checkpoint hash and the canonical RPC block hash trips a persistent fail-closed incident latch. The indexer does not guess a rewind depth or continue scanning.
- On a mismatch, every settled invoice is moved to `review`, every download entitlement is revoked immediately, and all pending/reconciled revenue rows move to `refund_review`. The cursor is preserved for forensic reconciliation.
- Subsequent scheduled runs remain halted without RPC scanning until a separately reviewed operator reconciliation/reset. There is no automatic unhalt.
- The authenticated `/v1/status` endpoint reports indexer state, checkpoint height, halt timestamp and reason without exposing signing or queue secrets. This is a status surface, not an external paging/alerting integration.
- New checkout invoice creation checks the persisted indexer state and returns `503` if the state row is missing or the incident latch is active. The public storefront is hidden under the same conditions, and authenticated status reports checkout as unavailable until the indexer is healthy again.
- Unknown orders, expired invoices, wrong token, wrong merchant, amount mismatch, wrong emitter, failed receipt, duplicate order payment, or malformed logs are quarantined. They never unlock a download.

## Security and production blockers

- Public checkout, indexer, legal-review and crypto-enablement gates remain disabled unless separately configured and approved.
- Migration `0007_base_usdc_reorg_halt.sql` adds the persistent incident latch columns to the indexer state.
- No deployed contract address, live Base RPC, production invoice signer, or real transaction has been verified in this task.
- The dedicated invoice signer key is security-critical and must not be the merchant wallet key. It has not been provisioned.
- The contract requires independent review and deployment approval. Do not deploy, sign, enable checkout or transfer funds without explicit authorization.
- Pakistan legal classification of this merchant payment flow remains unresolved. Obtain qualified Pakistan legal advice or written PVARA clarification before activating real crypto checkout.
- A mocked CI test is not a live wallet or chain rehearsal. No sale, customer payment, settled revenue, or production readiness is claimed.


## Base Sepolia test environment (test tokens only)

The indexer helpers now support a separately selected Base Sepolia environment for integration rehearsals:

- Chain ID: `84532`
- Circle USDC testnet token: `0x036CbD53842c5426634e7929541eC2318f3dCF7e`
- Official token reference: https://developers.circle.com/stablecoins/usdc-contract-addresses
- RPC URL: use an approved HTTPS Base Sepolia RPC endpoint.
- Set `BASE_CHAIN_ID=84532` and `BASE_USDC_TOKEN_ADDRESS=0x036CbD53842c5426634e7929541eC2318f3dCF7e`.
- Set `BASE_CHECKOUT_CONTRACT_ADDRESS` to the separately deployed `BaseUsdcDirectCheckoutSepolia` address and `BASE_DEPLOYMENT_BLOCK` to its actual deployment block.
- Use a dedicated test-only D1 database and test-only invoice signer. Never point a testnet indexer at the production database or reuse a production signer.
- Testnet USDC and testnet ETH have no financial value. The Circle faucet is documented at https://faucet.circle.com.

The public storefront and buyer checkout route remain **Base-mainnet-only**. A Base Sepolia indexer configuration cannot enable mainnet checkout. The testnet contract is a separate source artifact and is not deployed by CI.

This support does not imply a live testnet rehearsal: CI currently verifies network selection, typed-data domain separation, event decoding and local contract behavior with test doubles. An actual Base Sepolia deployment, wallet transaction and live RPC/D1 settlement rehearsal have not been performed.
