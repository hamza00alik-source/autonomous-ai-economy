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

## Stage 3: automatic master payout worker

`src/economy/profit_payouts.py` adds a worker that reads pending profit obligations, resolves the registered agent and master wallet addresses, requests the exact amount from a policy-enforcing signer using a stable idempotency key, asks an independent chain verifier to confirm final settlement, and only then marks the obligation paid. Failed broadcasts or verification leave the obligation pending for a later retry.

This is orchestration, not a live payment adapter. No production signer or chain verifier is included. The worker must be scheduled by the always-on runtime after those adapters are implemented. The signer must be idempotent for the supplied key and must enforce destination/amount limits independently of the agent model.

## Machine-to-machine service payments (x402)

The planned service-payment adapter will target x402 v2 rather than inventing a private HTTP payment format. x402 lets a client agent receive machine-readable payment requirements, select a supported scheme/network, authorize payment with its wallet signer, and retry the resource request with the signed payment. A service agent can expose a paid resource and receive settlement to its own configured wallet. x402 is a payment protocol, not a wallet, key manager, or autonomous business engine.

Implementation must use the official x402 SDK rather than manually constructing protocol headers. It must apply AAE's own per-agent destination allowlist and budget controls before signing, and must verify settled receipts before crediting revenue. Do not advertise a scheme/network until the configured facilitator or self-hosted settlement implementation confirms production support.

References:
- x402 v2 specification: https://github.com/x402-foundation/x402/blob/main/specs/x402-specification-v2.md
- Official Python SDK: https://github.com/x402-foundation/x402/tree/main/python/x402
- HTTP transport v2: https://github.com/x402-foundation/x402/blob/main/specs/transports-v2/http.md
- Solana agentic payments overview: https://solana.com/docs/payments/agentic-payments/x402

## Stage 4: provider-neutral wallet provisioning

`src/economy/wallet_provisioning.py` adds the first executable wallet lifecycle boundary:

- Each participant/role/network/asset tuple has one durable provisioning record.
- The external provider receives a stable idempotency key, so a retry after a timeout or process restart must return the same wallet rather than create another.
- Provider identity, network, asset and returned public address are checked before the address is registered in the finance ledger.
- Only the provider wallet reference and public address are stored. Private keys, seed phrases and signatures are not accepted or persisted.
- Repeated requests return the already-registered wallet; switching providers or silently replacing an address is rejected.

The included fake-provider tests exercise creation, idempotent repeat, retry after a simulated provider outage, provider mismatch and network mismatch. No real custody provider is selected or connected. Before production, the adapter must be implemented against a provider with documented idempotent wallet creation, isolated per-agent accounts, withdrawal policy controls, recovery procedures and auditable API credentials. Caller authentication and owner authorization must be enforced by the application boundary before invoking provisioning.

## Stage 5: finality-aware incoming chain monitor

`src/economy/chain_monitor.py` introduces a read-only chain-source interface and an incoming token-transfer monitor:

- Monitors only a configured network, asset and exact token contract, and only registered agent receiving addresses.
- Requires a valid transfer identity, source/destination, positive integer amount, block number/hash, canonicality, finality and confirmation count.
- Does not credit pending transfers. It credits only canonical transfers marked finalized by the adapter and meeting the configured minimum confirmations.
- Stores the provider cursor and each transfer identity, so replayed pages/notifications do not create duplicate revenue.
- Writes the finance event and monitor status in one SQLite transaction. A crash cannot leave a credited transfer with no monitor state (or vice versa).
- Rejects a transfer that would be assigned to an already-closed accounting period. Historical backfills need an explicit adjustment-period reconciliation.
- Detects a previously credited transfer disappearing or changing block identity and creates a persistent reorganization alert.
- An unresolved reorg alert blocks profit-period closure and blocks automatic master payouts, including when the alert is discovered after period close.

src/economy/evm_rpc.py now provides a read-only ERC-20 JSON-RPC adapter. It validates the configured eth_chainId, queries the exact token contract and registered destination topics, decodes Transfer logs, fetches each block timestamp/hash, derives confirmations from the latest block, and requires the RPC's finalized block tag. It pages by bounded finalized block ranges and fails closed when the RPC cannot provide the required data. The RPC URL, chain ID, network label, token contract and starting block are operator-supplied; no network or token is silently selected.

This adapter does not sign or broadcast transactions and contains no private keys. It is not yet connected to a production RPC endpoint. RPC providers are trust boundaries: production deployment still needs independent provider diversity or a trusted node, health monitoring, rate-limit/retry policy, chain-specific finality review and an operator-controlled historical backfill when new receiving addresses are registered. The current cursor is per network/token, so adding a new wallet after scanning has started requires an explicit backfill/reset procedure to avoid missing its older incoming transfers.

Reorg boundary: the adapter marks a returned log noncanonical when its block hash no longer matches the canonical block at that height, and the monitor blocks profit close/payout on resulting alerts. Standard eth_getLogs polling cannot by itself prove that a previously returned log has disappeared from a later response. A production-grade reorg reconciler must additionally compare a rolling canonical block/log history (or consume a trusted removed-log feed) and emit tombstones for previously credited logs that disappear. This reconciliation is not implemented yet.

**Important limitation:** the monitor deliberately does not reverse a credited receipt automatically after a deep reorganization. The alert remains active, and an operator note does not clear the hold. A separately audited compensating ledger adjustment and reconciliation workflow is still required before the alert can safely be cleared. The monitor supports a `period_resolver` callback that maps each observation's ISO-8601 block timestamp to its accounting period. The `period_id` argument is only a fallback for controlled tests or bounded scans; production must configure the resolver so historical pages cannot be assigned to the current period.

No production RPC endpoint is connected and no live money is moved by this stage.


## Stage 6: rolling canonical-history reorganisation reconciliation

`src/economy/reorg_reconciler.py` adds a bounded rolling verifier for already-credited receipts. On each run it obtains the RPC's finalized height, selects credited events in a configurable recent block window, and asks the chain adapter to verify the exact transaction receipt, canonical block hash, token contract, Transfer log index, sender, recipient and amount. A definitive mismatch changes the event to `reorg_alert`; it does not silently reverse accounting. RPC errors or malformed responses abort the run and leave event state unchanged.

The EVM adapter implements receipt verification using `eth_getTransactionReceipt` and `eth_getBlockByNumber`. It checks the receipt transaction hash and block identity, successful receipt status, exact ERC-20 log identity and transfer fields. The reconciler is a separate scheduled task: production must run it frequently enough for the chosen lookback window and monitor its health. Events older than the rolling window are not checked by each run; operators need a periodic deep audit or a longer lookback appropriate to the chain's reorg risk. A single RPC provider remains a trust boundary, and this component does not independently reverse ledger entries or clear alerts.

Tests cover canonical receipts, missing receipts, changed block hashes, definitive mismatch alerting, RPC failure fail-closed behavior and rolling-window bounds. No live endpoint, signer, private key or transfer is configured.
