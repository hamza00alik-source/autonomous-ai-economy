# Agent receiving wallets and direct payment requests

## What this milestone does

Each enrolled agent can be assigned one owner-authorized public receiving address for Base mainnet USDC. The authenticated AAE service can create an idempotent, expiring payment request for an agent. The current invoice and verification endpoints use the existing owner bearer token; dedicated per-agent credentials are not implemented.

Supported asset:
- Network: Base mainnet (chain ID 8453)
- Asset: native Circle USDC on Base
- Token contract: `0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913`
- Precision: 6 decimals

An owner signs the canonical receiving-wallet registration payload with the enrolled Ed25519 key. Only the public address, signature, and public metadata are stored. No private key, seed phrase, recovery phrase, or signing secret is accepted.

## Payment request and chain verification

Creating an invoice creates a payment instruction only. It does not prove that a buyer paid. The invoice remains `awaiting_payment` until an owner-authenticated verification request checks the transaction against a configured HTTPS Base JSON-RPC endpoint.

The verifier checks:
- Base mainnet chain ID 8453 and successful transaction receipt.
- The exact native USDC contract and ERC-20 Transfer event.
- The invoice receiving address and exact six-decimal amount.
- Receipt block hash and number against the canonical block.
- The RPC endpoint's `finalized` block has reached the receipt block.
- Payment timestamp is before invoice expiry.

Exact, timely, finalized payments become `confirmed`. Underpayments, overpayments, and late payments are retained as immutable evidence with status `review`. Failed, missing, wrong-chain, non-finalized, or noncanonical transactions are not confirmed. A transaction hash can be bound to only one invoice.

The verifier uses one configured RPC endpoint (`BASE_RPC_URL`). This is stronger than trusting a buyer screenshot or callback, but it is not a trustless multi-provider oracle. Production should use independently operated RPC sources and monitoring.

## Asset-aware receipt journal

A separate asset-aware journal now supports Base USDC without mislabeling it as USD. Once an invoice has an exact confirmed chain observation, the service posts a balanced, idempotent journal transaction:
- Debit: agent pending-custody account associated with the receiving address.
- Credit: agent pending-revenue account.

The owner dashboard exposes this amount as **Pending wallet control**. This is a record of confirmed token transfers to the registered address; it is not a spendable agent balance. The existing USD simulated-spending policy, reservations and scheduler are not silently reused for USDC.

The journal will not post from an invoice status alone: the database requires immutable, confirmed chain-observation evidence. Journal transactions and postings are append-only. Duplicate verification attempts reuse the same idempotent journal entry.

## Wallet control and remaining autonomy

The owner-authorized address registry does not prove that the AI controls the receiving wallet. A public address is not a private signing capability. The AI never receives the private key.

Still required before the agent can independently use received funds:
1. Prove wallet control or provision an agent-owned smart account through a suitable restricted signer.
2. Give each agent a dedicated authenticated identity and narrowly scoped API capability.
3. Add owner-signed USDC allocation/spending policies and asset-aware reservations and limits.
4. Execute transfers through a restricted signer or smart account, with on-chain transaction verification and replay protection.
5. Complete Pakistan legal/provider eligibility review before live commercial activation.

No USDC is currently marked available or spendable, no budget is funded, no product is automatically delivered, and no outgoing transfer is implemented.

## Activation boundary

This code is not deployed. The existing production Worker and D1 database are unchanged. No live checkout is enabled and no payment provider account is created. Owner/operator enrollment, migrations, wallet registration, RPC configuration, legal review, and production approval remain separate gates.
