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
- D1 writes for event persistence, invoice settlement, revenue attribution and delivery entitlement must be atomic. If any write fails, the entire settlement transaction must roll back and be safely retryable.

## Work still required

- Implement and unit-test EIP-712 invoice signing with a maintained Ethereum library; do not implement elliptic-curve signing manually.
- Add private invoice creation and status endpoints with owner authentication and strict fixed product/price mapping.
- Implement JSON-RPC polling, ABI log decoding, receipt verification, confirmation handling, backfill, cursor persistence and reorg recovery.
- Implement a wallet checkout page that displays Base and native USDC clearly and asks only for exact approval.
- Add integration tests against a local EVM or controlled Base testnet rehearsal.
- Independently audit the Solidity contract and the full Worker/indexer flow.
- Obtain qualified Pakistan legal review or written PVARA clarification for the actual merchant and payment flow.
- Obtain explicit approval before provisioning a signer, deploying a contract, enabling a public checkout, publishing a product, or moving funds.

## Safety status

This migration is a database foundation only. It does not prove payment acceptance, customer demand, product sales, revenue, production readiness, or legal eligibility. Existing public checkout and outbound payout gates must remain off.