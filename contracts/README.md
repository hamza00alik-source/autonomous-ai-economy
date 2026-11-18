# Base USDC direct checkout — engineering proposal

## Status

Undeployed, experimental and unaudited. Not a live checkout and not approved for production. No wallet signature, transaction, gas spend, token transfer, customer payment or deployment is performed by this change.

## Pinned network and asset

- Network: Base mainnet, chain ID `8453`.
- Asset: Circle native USDC; contract `0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913`.
- Precision: 6 decimals. Bridged USDbC is not accepted.
- Circle's current supported-chain listing confirms the exact native Base address: https://help.circle.com/support/en/usdc-supported-blockchains-minting-redemption-faqs?id=kb_article_view&sysparm_article=KB0010590

## Contract security model

`src/BaseUsdcDirectCheckout.sol` is deliberately narrow:

1. Constructor only succeeds on Base mainnet.
2. Merchant recipient and invoice signer are immutable, non-zero addresses.
3. AAE's invoice signer must sign an EIP-712 invoice binding the domain (chain and deployed contract), unique order ID, exact USDC base-unit amount, deadline, and merchant recipient.
4. Buyer approves the exact amount and calls `pay(orderId, amount, deadline, signature)`.
5. Contract validates the signer, deadline, amount-bound signature and unused order ID before transfer.
6. USDC transfers directly from buyer to merchant. The contract has no owner, custody balance, admin, arbitrary-call or withdrawal method.
7. The contract checks the merchant's balance delta and emits `OrderPaid`.

This closes the earlier order-poisoning weakness: a caller cannot reserve a public order ID using a self-selected tiny amount. An invalid amount or altered order ID fails signature validation. The invoice signing key is security-critical: keep it separate from the merchant wallet, restrict it to invoice signing, store it only as a managed secret, rotate it through a reviewed redeployment process, and never commit it to source control. It cannot transfer merchant funds through this contract.

The buyer needs Base ETH for gas and a wallet supporting Base. The future checkout UI must request exact-amount approval only and explain both transactions.

## Required server-side event indexer before delivery

Never trust a browser redirect, buyer-supplied transaction hash, token symbol or unconfirmed log. A production indexer must independently verify:

- chain ID 8453 and the exact reviewed deployment address;
- successful transaction receipt and canonical block;
- event emitter and exact event signature `OrderPaid(bytes32,address,address,uint256,address)`;
- order ID maps to one pending AAE invoice;
- buyer, merchant and native USDC addresses match the invoice and deployment configuration;
- amount equals the invoice's signed amount in USDC base units;
- configured confirmation/finality threshold is reached;
- unique chain/transaction/log identity is atomically persisted before fulfillment.

Backfill from a recorded deployment block, persist a block cursor and block hashes, detect parent-hash changes, and re-check recent blocks after a reorg. Duplicate, unknown, expired, underpaid, wrong-token, wrong-recipient or mismatched events must be quarantined and must never unlock a download. The invoice database must use unique constraints for order IDs and chain/transaction/log identity.

Only after verification should AAE atomically settle the invoice, create revenue attribution, and issue the existing short-lived hashed download credential.

## Launch gates

- Foundry tests are regression tests, not an independent audit.
- CI must pass before review.
- Independent Solidity security review and testnet rehearsal are required.
- Confirm merchant address and separately provision the invoice-signing key under an approved secrets process.
- Obtain qualified Pakistan legal review or written PVARA clarification for this exact merchant/payment flow before accepting real crypto. PVARA publishes the Virtual Assets Act 2026 and implementing regulations; VASP licensing depends on the actual activity and legal classification. See https://www.pvara.gov.pk/regulations and https://www.pvara.gov.pk/licensing.
- Do not deploy from CI. Do not place private keys, seed phrases, RPC secrets or signing credentials in source code or GitHub Actions.
- Keep public checkout disabled until legal clearance, independent audit, successful testnet rehearsal, and explicit owner approval.
- Never let an agent transfer or sweep merchant funds.

## Current integration boundary

This PR contains the signed-invoice on-chain primitive, Foundry regression tests, CI workflow and this design record. It does not yet connect the Cloudflare Worker, provision an invoice signer, create a Base RPC event indexer, implement wallet checkout UI, publish a product, or enable payment collection. No sales or revenue are claimed.
