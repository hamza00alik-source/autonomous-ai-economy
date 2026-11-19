# Agent receiving wallets and direct payment requests

## What this milestone does

Each enrolled agent can be assigned one owner-authorized public receiving address for Base mainnet USDC. The address is stored separately from the agent's internal accounting account. The authenticated AAE service can create an idempotent, expiring payment request for an agent; the current endpoint is protected by the existing owner bearer token, not a dedicated per-agent credential.

The supported asset is deliberately narrow:
- Network: Base mainnet (chain ID 8453)
- Asset: native Circle USDC on Base
- Token contract: `0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913`
- Precision: 6 decimals

An owner must sign the canonical receiving-wallet registration payload with the enrolled Ed25519 key. Only the public address, signature, and public metadata are stored. No private key, seed phrase, recovery phrase, or signing secret is accepted.

## Critical distinction: a payment request is not a received payment

Creating an invoice only creates a payment instruction. It does not prove that a buyer paid, that the transaction succeeded, or that the agent controls the destination key. The invoice remains `awaiting_payment`. No journal entry, revenue event, budget credit, or product delivery is triggered by invoice creation.

Independent chain observation is still required. A later settlement verifier must validate the Base transaction receipt, USDC contract, recipient, transfer event, amount, block finality, chain reorganization risk, and duplicate/reversal handling before any funds are reconciled. Until that exists, the system must not mark these invoices paid.

## Wallet control

This is an owner-authorized public-address registry, not proof that an AI legally owns the wallet, a wallet generator, or a signer. The address must already belong to a merchant-controlled wallet or an approved restricted signing service. The AI never receives the private key. Dedicated agent authentication, policy-limited transaction signing, outgoing transfers, and autonomous wallet operations are not implemented.

## Remaining autonomy work\n\nThis milestone lets the AAE service issue a direct-payment instruction for an agent-associated address. It does not yet let an independently authenticated agent call the invoice API without the owner service credential, observe chain events, or control funds after receipt. Those require agent-scoped credentials, an independent Base chain observer, a restricted signer/smart-account design, and asset-aware settlement/allocation accounting.\n\n## Activation boundary

This code is not deployed. The existing production Worker and D1 database are unchanged. No live checkout is enabled and no payment provider account is created. The existing NOWPayments integration remains a separate provider route and is not selected for Pakistan merchant use. Owner/operator enrollment, migration, wallet registration, chain verification, legal review, and production approval remain separate gates.
