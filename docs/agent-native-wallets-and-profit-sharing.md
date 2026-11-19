# Agent-native wallets and automatic profit sharing

## Goal

Agents operate as economic participants rather than having every sale routed through a human-oriented checkout. Each agent has a public receiving address per supported network and asset. A trusted chain adapter monitors that address, verifies settled transfers and attributes receipts to the agent. An agent may use an external policy-bound signer to pay for its own approved operating costs. After a closed accounting period, the system retains an operating reserve, keeps the agent's share and creates an automatic payout obligation for the master.

The master share is a configured economic agreement, not a default percentage. Set it explicitly per deployment. Example only: $1,000 verified income less $200 verified expenses gives $800 operating profit; a 10% reserve leaves $720 distributable. At a 50% owner share, $360 is due to the master and $360 remains with the agent.

## Current implementation in this change

- `src/economy/agent_finance.py` stores separate agent/master public wallet addresses, records adapter-verified on-chain cashflows idempotently, closes profit periods, calculates reserves and master/agent allocation, and tracks a pending/paid owner distribution.
- It requires a verified transfer record and exact registered destination. Duplicate network/transaction/transfer references are rejected.
- Period close is idempotent. A later call cannot silently change the already-closed allocation.
- The master payout is not marked paid until an independently verified transaction to the registered master address is supplied.
- This is a chain-agnostic accounting/control layer. It does not yet create blockchain addresses, monitor a chain, sign transactions, broadcast transfers, or hold private keys.

## Runtime design required to make agents operate without per-transaction human approval

1. **Wallet provisioner:** create one isolated smart account/address per agent and network. Persist only public addresses and wallet metadata here.
2. **Chain monitor:** subscribe/poll for incoming token transfers; verify token contract, chain ID, destination, amount, transaction inclusion, confirmations/finality and reorgs. Only this adapter may construct trusted normalized receipts.
3. **Agent payment protocol:** expose machine-readable service prices and accept direct wallet payments. x402 can be one HTTP payment protocol adapter; it is not itself a wallet.
4. **Policy-bound signer:** keep signing keys outside model prompts and the application database (MPC/HSM/TEE or a reviewed smart-account signer). Enforce per-transaction, daily and monthly limits, destination allowlists, asset/network allowlists, nonce/replay protection and emergency pause at the signer boundary.
5. **Autonomous operations budget:** agents can pay approved compute, model, data and subcontractor costs from their own wallet without asking the owner for each routine payment. The signer denies anything outside the preconfigured budget/policy. Owner approval is required only to establish/change the policy or for exceptional high-risk operations.
6. **Profit close and distribution:** reconcile receipts, expenses, refunds, network/provider fees and tax liabilities; reserve the configured percentage; split the remaining realized profit; broadcast the master's share automatically; verify the payout and mark it paid. Failed payouts remain pending and retry safely with transaction idempotency.
7. **Governance:** the master configures ownership/beneficiary, share, reserve and risk policy. Agents cannot change these fields or redirect the master's payout address. Include pause, recovery and audited wallet rotation.

## Safety and legal boundaries

A public address can receive funds while the agent is offline. Spending requires a signer and must never expose a seed phrase/private key to an LLM. A wallet address does not make an AI a legal person or establish legal ownership; the accountable operator, tax treatment and beneficiary arrangement must be documented. Do not enable live transfers until the chosen network/provider, local legal position, wallet security and recovery process have been reviewed.

NOWPayments may remain as an optional customer checkout bridge, but it is not the agent's wallet and is not the core agent-to-agent payment architecture. No live chain adapter, wallet signer, real transfer or revenue is shipped by this change.

## Stage 2: routine autonomous spending controls

`src/economy/wallet_spending.py` adds an owner-configured per-agent spend policy. The owner sets supported network/asset, daily cap, per-transaction cap and explicit destination allowlist once. The agent can reserve routine spending within that policy without a per-transaction human approval. The store counts reserved, broadcast and settled transfers against the daily budget, supports emergency pause, and requires exact independently verified settlement before marking a spend settled.

This is still not a signer or live wallet. The production signer must enforce the same policy at the custody boundary; application-level checks alone are not sufficient. The current module intentionally does not generate keys, sign, broadcast, monitor chains, or invoke x402. A future adapter will connect the policy reservation to a reviewed smart-account/MPC/HSM signer and chain monitor.
