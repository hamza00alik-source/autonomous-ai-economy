# Base USDC Worker integration — staged design

## Current status

The 0006_base_usdc_checkout.sql migration creates a separate Base-native USDC ledger. It is intentionally dormant: no Worker route reads or writes these tables, no RPC calls are made, no signer key is configured, and no public checkout or fulfillment path is enabled.

The existing NOWPayments path is kept unchanged. It is not treated as the worldwide provider decision.

## Required runtime configuration (not provisioned)

A future implementation will require all of the following, with values reviewed before use:
- BASE_RPC_URL: HTTPS Base mainnet JSON-RPC endpoint.
- BASE_CHECKOUT_CONTRACT_ADDRESS: exact independently reviewed deployed contract address.
- BASE_DEPLOYMENT_BLOCK: verified deployment block, used as the backfill start.
- BASE_CONFIRMATIONS: conservative confirmation threshold.
- BASE_INVOICE_SIGNER_PRIVATE_KEY: dedicated invoice-only key, never the merchant wallet key.

No such values are assumed by this migration. Never store secrets in this file, Git, workflow logs, or client code.

## Invoice lifecycle

1. The private Worker creates a server-priced order; it does not accept buyer-supplied product IDs or amounts.
2. It generates an unpredictable order ID and a random buyer download credential; only the credential hash is stored.
3. A dedicated signer signs the EIP-712 invoice for the exact order ID, exact USDC base-unit amount, deadline, chain and contract domain, and immutable merchant.
4. The invoice row is inserted idempotently before returning the signed invoice to the buyer.
5. The buyer wallet requests an exact allowance and calls the deployed contract. No unlimited allowance is requested.
6. The Worker indexer independently observes chain logs. Browser redirects and buyer-supplied transaction hashes are never proof of payment.
7. The indexer validates chain, contract emitter, event signature, native USDC token, merchant, exact amount, order ID, successful receipt, canonical block and confirmation threshold.
8. Only a fully validated event may atomically mark the invoice settled, persist the unique chain/transaction/log event, create the revenue attribution, and set the seven-day delivery window.
9. The buyer can download only with the original bearer credential and only while the invoice is settled and access is unexpired.

## Reorg, duplicates and mismatches

- The event primary key is (chain_id, transaction_hash, log_index).
- Invoice transaction hash is unique because the checkout contract emits one payment event per pay call.
- The indexer cursor stores the next block and last observed block hash.
- Re-check a rolling recent block range and parent hashes; orphaned events must revoke access and move revenue to review/reversal rather than remain settled.
- Unknown orders, expired invoices, wrong token, wrong merchant, amount mismatch, wrong emitter, failed receipt, duplicate order payment, or malformed logs go to quarantine. They never unlock a download.
- A D1 batch settlement helper now matches the event to the invoice, checks the canonical block timestamp against invoice expiry, and writes the event, seven-day download entitlement and gross revenue attribution together. It is unit-tested with a fake D1 adapter; live D1 integration and failure/retry tests remain required.

## Work still required

- EIP-712 signing helper is implemented with viem and tests recover the configured signer; it still needs a gated invoice-creation endpoint and dedicated key provisioning.
- Add private invoice creation and status endpoints with owner authentication and strict fixed product/price mapping.
- Base RPC client, bounded confirmed-log scanning, ABI decoding, receipt/block canonicality and confirmation-depth checks are implemented and unit-tested. A five-minute scheduled Worker hook now calls the indexer only when AAE_BASE_USDC_INDEXER_ENABLED is explicitly true; it persists a cursor, scans from the configured deployment block, and rewinds a recent window on a detected reorg, revoking affected entitlements and moving revenue to review.
- Implement a wallet checkout page that displays Base and native USDC clearly and asks only for exact approval.
- Add integration tests against a local EVM or controlled Base testnet rehearsal.
- Independently audit the Solidity contract and the full Worker/indexer flow.
- Obtain qualified Pakistan legal review or written PVARA clarification for the actual merchant and payment flow.
- Obtain explicit approval before provisioning a signer, deploying a contract, enabling a public checkout, publishing a product, or moving funds.

## Safety status

This is still a staged integration, not production checkout. Signing, event decoding, bounded RPC scanning, finality verification and a D1 settlement helper now exist as tested modules, but they are not connected to Worker routes or the scheduled trigger. No live RPC, D1 settlement, wallet checkout, buyer download, customer sale, revenue, production readiness or legal eligibility has been demonstrated. Existing public checkout and outbound payout gates must remain off.