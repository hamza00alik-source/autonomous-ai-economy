# Base USDC direct checkout — engineering proposal

## Status

This is an undeployed, experimental payment primitive. It is not a live checkout and is not approved for production. No wallet signature, transaction, gas spend, token transfer, customer payment, or deployment is performed by this change.

## Pinned network and asset

- Network: Base mainnet, chain ID `8453`.
- Asset: Circle native USDC.
- Contract: `0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913`.
- USDC precision: 6 decimal places.
- Do not accept bridged USDbC or any token selected by symbol alone.
- Official issuer reference: https://www.circle.com/blog/usdc-now-available-natively-on-base
- Circle's supported-chain documentation: https://developers.circle.com/circle-mint/supported-chains-and-currencies

## Contract behavior

`src/BaseUsdcDirectCheckout.sol` is intentionally narrow:

1. Constructor only succeeds on Base mainnet and stores a non-zero merchant address immutably.
2. The only payment asset is the hard-coded native Circle USDC contract above.
3. Buyer approves this contract for the exact amount, then calls `pay(orderId, amount)`.
4. USDC is transferred directly from buyer to merchant. The checkout contract has no token balance, owner, admin, pause, rescue, arbitrary-call, or withdrawal function.
5. A unique non-zero `bytes32` order ID can be paid once.
6. The contract checks the merchant's USDC balance delta equals the requested amount and emits `OrderPaid`.

The buyer must have enough Base ETH for gas and must use a wallet that supports Base. The payment UI must explain the approval and payment transactions clearly; no unlimited approval should be requested.

## Required server-side verification before digital delivery

A future AAE indexer must not trust a browser success redirect, buyer-supplied transaction hash, token symbol, or unconfirmed log. It must independently verify all of the following from a trusted Base RPC/indexer:

- chain ID is 8453;
- transaction and receipt are successful and canonical;
- configured checkout contract address is the reviewed deployment;
- log emitter is exactly that contract;
- event signature is exactly `OrderPaid(bytes32,address,address,uint256,address)`;
- order ID matches one pending AAE invoice and has not already been fulfilled;
- buyer, merchant, and token addresses match the invoice and immutable deployment configuration;
- amount equals the invoice amount in USDC base units (6 decimals), with no rounding tolerance;
- receipt has reached the configured confirmation/finality threshold;
- transaction/log identity is unique and atomically recorded before delivery.

Only after verification should AAE atomically mark the invoice settled and issue the existing short-lived, hashed download credential. Duplicate logs, reorgs, underpayments, wrong assets, wrong recipients, unknown orders, and mismatched amounts must remain quarantined and must never unlock a download.

The indexer must backfill from a stored deployment block, persist a block cursor, detect parent-hash changes, and re-check recent blocks after a reorg. Use unique database constraints for both order ID and chain/transaction/log index.

## Security and operational gates

- The Solidity tests are regression tests, not an audit.
- Before deployment: independent Solidity security review, testnet rehearsal with a separately configured test contract/token, exact merchant-address confirmation, and legal review of the Pakistan Virtual Assets Act/PVARA applicability to the actual flow.
- Do not deploy from this repository's CI.
- Do not place private keys, seed phrases, RPC secrets, or signing credentials in source code or GitHub Actions.
- Production checkout must remain disabled until owner approval, legal clearance, security review, successful testnet rehearsal, and an explicit production configuration review.
- Never let an agent transfer or sweep merchant funds. The contract has no such capability by design.

## Current integration boundary

This PR adds only the on-chain payment primitive and its automated Solidity tests. It does not modify the Cloudflare Worker, create invoices, run a Base RPC indexer, create a checkout UI, configure secrets, publish a product, or enable payment collection. The existing NOWPayments path remains unchanged and separately gated.
