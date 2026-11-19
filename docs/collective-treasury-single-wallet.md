# AAE collective treasury (single on-chain wallet)

## Decision

AAE uses **one real shared on-chain treasury wallet** for the configured network/asset pair, with a separate capped agent account in the accounting ledger. For the first deployment, the intended asset is USDC on Base. Every agent receives the same actual public treasury address to receive funds; each agent can spend from that address through the policy-bound treasury signer. Agents do not receive separate private keys or independent on-chain accounts. Each agent's USDC balance is hard-capped at **$500 (500,000,000 USDC base units at 6 decimals)**, including pending incoming payment intents. The cap is enforced transactionally when intents are created, receipts are credited, suspense receipts are allocated, and spends are reserved. The cap is not an LLM instruction or dashboard-only warning.

The current provider adapter is Coinbase Developer Platform (CDP) Server Wallets. CDP manages the EVM account and signing infrastructure; AAE stores only the provider account reference and public address. CDP's Python SDK supports server-managed EVM accounts, account policies and USDC transfers on Base/Base Sepolia. The optional dependency is installed with `pip install '.[cdp]'`.

## What was added

- `src/economy/collective_treasury.py`
  - A single registered treasury address per network/asset; attempts to replace it are rejected.
  - Agent virtual accounts, a hard $500 USDC balance cap per agent, daily and per-transaction budgets, destination allowlists and emergency pause.
  - `agent_wallet(agent_id, network, asset)` returns the actual shared public wallet address plus the agent's gross ledger balance, spendable balance and cap; it never returns keys or signing credentials. All agents on the same network/asset receive the same address.
  - Incoming payment intents reserve cap capacity before a payer is instructed to send; duplicate intents are idempotent. Finalized receipts and later suspense allocations recheck the cap inside the same database transaction.
  - Virtual balance attribution for incoming receipts, suspense/unallocated deposits, expenses, master share and operating reserves.
  - Separate verified pool-event ledger tracking pooled receipts minus external expenses, plus a reconciliation snapshot comparing pooled cash events with the sum of all virtual accounts.
  - Idempotent receipt identity using network + transaction hash + transfer/log reference.
  - Payment-attribution reference matching before an unallocated receipt can be assigned to an agent.
  - Spend reservation before signing; exact source, destination, asset and amount must match independently verified settlement.
  - Ambiguous broadcast outcomes are held as `uncertain`; they cannot be cancelled or blindly retried.
  - Period close calculates net realized profit, reserves and owner share, then moves virtual ledger balances. It refuses to close while any settled agent spend lacks a finalized gas receipt and a timestamped USDC valuation.
- `src/economy/agent_wallet.py` exposes an identity-bound `AgentTreasuryWallet` capability for each agent: `wallet()` returns the actual shared public address and capped balance; `prepare_receive()` creates an exact amount + payer-bound receive instruction; `request_spend()` reserves a policy-compliant transfer for the treasury worker. The facade never exposes signer/key material or lets the agent choose another agent's ID.
- `CDPServerTreasuryWallet`
  - Reuses one stable named CDP EVM account, binds the required restrictive CDP account policy, and returns its public address.
  - Sends USDC from the shared account using CDP's server-managed signer.
  - Never reads, exports or stores private keys.
- `economy-treasury` CLI provisions/retrieves and registers the one shared wallet.
- `src/economy/evm_rpc.py` reads finalized transaction receipts and calculates execution gas plus Base L1-data and optional blob fees in wei, after chain-ID, finality and canonical-block checks.
- `CollectiveTreasuryStore.record_gas_cost()` binds that verified fee to the exact settled spend reservation and records the externally supplied USDC valuation, price source and observation time. Gas is included in period expenses but does not incorrectly debit the USDC pool because it was paid in native ETH.
- `src/economy/treasury_worker.py` adds a bounded one-shot worker that picks up only fresh reserved spends. The store's atomic compare-and-set claim prevents two workers from submitting the same reservation; uncertain transactions are never resubmitted by this worker.
- `src/economy/collective_treasury_monitor.py` scans incoming finalized transfers, binds payment intents to expected payer addresses, attributes only unique exact matches, holds ambiguous receipts in suspense, and requires a strict-majority quorum of independent RPC pages.
- `tests/test_collective_treasury_monitor.py` covers exact attribution, ambiguity, replay safety, changed block identity, and quorum disagreement.
- `tests/test_collective_treasury.py`, `tests/test_evm_rpc.py` and `tests/test_treasury_worker.py` cover shared-wallet uniqueness, suspense attribution, receipt deduplication, spend controls, atomic claims, worker limits, settlement, gas fee finality, Base L1/blob fee arithmetic, valuation gating and profit allocation.

## Why attribution is mandatory

An ERC-20 USDC transfer to one common address does not contain a free-form agent identifier. The destination alone cannot tell AAE whether Agent A, Agent B or another agent earned the money.

AAE requires a payment intent before it can credit an agent. `create_payment_intent()` records the intended agent, network, asset, exact amount and unique attribution reference. A receipt can be credited directly only when it matches a still-pending intent exactly. A reference cannot be reused, assigned to another agent, or used for a different amount.

1. A trusted payment integration creates the intent, correlates it to the payer/request, and supplies the verified attribution reference alongside independently verified chain evidence. AAE checks the intent and credits the named agent.
2. If a verified transfer arrives without an intent reference, AAE credits `treasury:unallocated`. It can only be allocated later if its stored reference matches a pending intent for that exact agent, network, asset and amount. An unknown deposit is never guessed or silently credited.

Important trust boundary: the on-chain ERC-20 Transfer event itself does not contain AAE's internal invoice reference. The payment-intent adapter must securely correlate the intent to the exact transaction (for example through a verified x402/payment-facilitator result or a payer-and-amount match). A caller-supplied string without that trusted correlation is not proof of ownership.

## Provisioning prerequisites

1. Create a Coinbase Developer Platform project and create an API key plus Wallet Secret.
2. Create a restrictive EVM account policy in CDP. It must limit the allowed network/USDC contract, destination addresses and spend amounts/rates appropriate to the treasury. Review the actual policy in the CDP console; AAE cannot infer whether an arbitrary policy ID is safe.
3. Provide secrets only through the deployment's secret manager or protected runtime environment. Never paste them into chat, commit them, or put them in agent prompts:
   - `CDP_API_KEY_ID`
   - `CDP_API_KEY_SECRET`
   - `CDP_WALLET_SECRET`
   - `AAE_CDP_ACCOUNT_POLICY_ID`
4. Install the optional SDK and provision on Base Sepolia first:

   ```bash
   pip install '.[cdp]'
   economy-treasury --network base-sepolia
   ```

5. The CLI returns the public address and stores it in `data/collective_treasury.sqlite3`. Verify the address in the CDP console and on a Base Sepolia explorer before funding it. Wallet creation does not fund it and does not move money.
6. Only after testnet end-to-end verification, review CDP policy, custody terms, recovery, compliance and legal requirements. Mainnet provisioning requires the explicit command:

   ```bash
   economy-treasury --network base --confirm-mainnet
   ```

The account is EVM-address based and may be used on Base Sepolia or Base. The local ledger stores a network/asset-specific treasury registration. Do not treat testnet USDC as real money.

## Operational contract

- All customer/agent receipts go to the same treasury address.
- The Accounting Agent owns attribution and virtual ledger updates; it does not own signing keys.
- An agent may request a spend without asking the owner for every routine transaction. AAE checks its virtual balance, the $500 USDC maximum balance, budget, destination allowlist and pause status. Each agent is shown the shared treasury's actual public address for receiving funds; all agent-originated transfers are sent from that same address and attributed to the requesting agent in the internal ledger. The external CDP account policy must independently constrain the signing account.
- A spend is not an expense until the chain verifier confirms the exact transaction and finality. The executor durably holds the reservation before submission, persists a returned transaction hash, and exposes a `reconcile()` path that verifies an existing transaction without broadcasting again. If a provider times out before returning a hash, the operator must discover the transaction from CDP/chain history before reconciliation; never blindly retry.
- Period close is blocked while the agent has unresolved reserved, broadcast or uncertain spends.
- The treasury's on-chain balance is the actual pooled asset balance. AAE's `pool_balance()` is only the ledger-tracked pool (verified receipts minus verified external expenses); `reconciliation_snapshot()` checks that this matches the sum of virtual agent/treasury accounts. A separate live RPC/CDP balance check is still required to reconcile the ledger against the actual on-chain USDC balance. Virtual agent balances are internal accounting claims against that pool, not separate segregated assets or legal ownership rights.
- Never allow the sum of virtual liabilities, reserves and pending obligations to exceed reconciled treasury assets. Add a periodic full-balance reconciliation and alerting before production operation.
- A common wallet creates commingling and concentration risk. Use strict policies, independent transaction monitoring, a master emergency pause, protected database backups, dual control for policy/address changes, and a documented recovery process.
- The implementation provides the core ledger, exact payment-intent matching, CDP wallet provisioning/transfer adapter, and callable `CollectiveTreasuryPaymentExecutor`. The executor reserves/holds an agent spend before contacting CDP, persists known transaction hashes, and settles only after an injected verifier confirms the exact on-chain transfer. Its reconciliation path verifies an existing transaction without resubmitting. An ambiguous provider response remains held and is never blindly retried. The incoming receipt monitor now connects finalized chain observations to the collective ledger, but a production RPC quorum wrapper, daemon/scheduler, customer invoice API and continuous Accounting Agent runtime are still follow-up work.

## On-chain balance reconciliation

The ledger's own pool/virtual-account equality is necessary but not sufficient: it cannot detect an unrecorded external transfer or an incoming deposit that has not yet been ingested. The read-only reconciliation command queries finalized `balanceOf(treasury_address)` and the finalized native ETH balance from at least two configured RPC endpoints. It compares the agreed raw USDC amount to the internal pool ledger and reports the ETH gas reserve.

Configure `AAE_EVM_RPC_URLS` as a comma-separated list of at least two independently operated RPC endpoints, then run:

```bash
economy-treasury-reconcile \
  --network base-sepolia \
  --chain-id 84532 \
  --asset USDC \
  --token-contract 0xYOUR_BASE_SEPOLIA_USDC_CONTRACT \
  --minimum-native-balance-wei 1000000000000000
```

For Base mainnet, use chain ID `8453` and the official Base USDC contract address. The token contract must match the actual asset you use. The command is read-only; it never signs or broadcasts. It exits non-zero if providers disagree, if the chain balance, pool ledger and virtual accounts do not reconcile, or if native ETH is below the configured gas reserve. A single EVM address can hold both USDC and ETH, so this remains one shared wallet. USDC transfers from this server-managed EOA require native ETH for network gas. Successful AAE treasury spends now have a gas-fee accounting path: `transaction_fee_wei()` verifies a finalized canonical receipt and includes execution gas, Base `l1Fee` and optional blob fee; a trusted backend must then provide the USDC valuation and timestamp to `record_gas_cost()`. Profit close is blocked if a settled spend is missing either record. This does not yet reconcile every possible wallet-originated transaction (for example, unrelated/manual or failed transactions); keep production distributions disabled until the transaction inventory and valuation source are independently operated and audited. Run reconciliation under an external scheduler and alert on non-zero exit status. Multiple RPC URLs do not guarantee independent infrastructure; choose providers with separate operators/infrastructure.

## Important provider limitation

The CDP transfer SDK call does not expose an AAE idempotency key in this adapter. If a transfer request times out after submission, the caller must search/reconcile the provider and chain state before retrying. The AAE spend reservation can be held in `uncertain` state for that purpose. Do not build blind automatic retries around an ambiguous transfer.

## Sources

- Coinbase CDP Python SDK: https://coinbase.github.io/cdp-sdk/python/
- CDP Wallet API quickstart: https://docs.cdp.coinbase.com/wallet-api/docs/quickstart
- CDP SDK source: https://github.com/coinbase/cdp-sdk


## Continuous Accounting Agent runtime and treasury reorg guard

`src/economy/collective_accounting_runtime.py` adds the guarded accounting cycle. It performs, in order:

1. Poll the incoming treasury receipt monitor.
2. Recheck credited receipts against canonical chain history using the independent-provider `QuorumEVMVerifier`.
3. Run the injected on-chain balance reconciliation callback.
4. Execute a bounded batch of reserved agent payments only if balance reconciliation reports `fully_reconciled: true` and there are no open reorganization alerts.

The runtime exposes `run_once()` for a scheduler and `run_forever()` for a supervised service process. The default interval is 30 seconds. It logs failed cycles and waits until the next interval; it does not bypass a failed safety gate. Use a process supervisor (restart policy, health monitoring, log collection and restricted secret injection) and configure separate RPC operators for the receipt quorum and canonicality quorum. Distinct URLs alone do not prove independent infrastructure.

A reorganization mismatch creates a durable `treasury_reorg_alerts` incident and disables every agent spend policy for the affected network/asset. The ledger is **not** automatically reversed: that would risk corrupting closed accounting periods or double-debiting funds. An operator must investigate the canonical chain and ledger, record a resolution note using `resolve_reorg_alert()`, then explicitly resume agents one at a time using `resume_agent_after_review()`. Resolving an alert does not itself resume spending. Old monitor records that predate stored block heights are treated as unverifiable and trigger a freeze requiring review.

The runtime is a reusable orchestration component, not yet a turnkey hosted daemon: the deployment host must construct the RPC quorum sources, CDP signer, transfer verifier, gas-fee valuation service and multi-RPC balance-check callback, then start `run_forever()`. No live credentials or provider configuration are committed to this repository. Testnet end-to-end wiring and CI verification remain required before enabling real funds.

## Incoming collective treasury receipt monitor

`CollectiveTreasuryReceiptMonitor` in `src/economy/collective_treasury_monitor.py` scans verified ERC-20 transfer observations addressed to the one registered treasury wallet and records them in the collective pool ledger. The monitor is injected with a `TreasuryReceiptSource`; use a source that independently validates chain ID, token contract, canonical block identity and finality. `QuorumTreasuryReceiptSource` requires a matching page and cursor from a majority of at least two independently operated sources and fails closed on disagreement. Wrap separate `EVMJSONRPCSource` instances with it before enabling automatic attribution. This strict page quorum can stall if provider finalized heights differ; align their scan configuration and investigate disagreement rather than lowering quorum to bypass it.

A payment intent can be bound to an expected payer address with `bind_payer(attribution_ref, payer_address)`. The binding is immutable. A finalized deposit is credited to an agent only when exactly one pending intent matches the payer address, network, asset and exact amount. If there is no match or more than one match, the deposit is credited to `treasury:unallocated`; the monitor never guesses. This is a practical on-chain correlation rule, not a memo embedded in the ERC-20 transfer. A customer should be instructed to pay from the bound address and for the exact amount. If a payer uses a different address or sends a partial amount, the funds remain in suspense for operator resolution.

The monitor persists a block cursor and event identities. If a page is replayed after a crash, it accepts only an exact previously recorded receipt; conflicting reuse stops processing. It is currently a callable one-shot component, not a continuously running service. The deployment scheduler must invoke it regularly and alert on failures. Reorg monitoring must continue independently; do not treat one successful receipt poll as permanent finality.
