# Base Sepolia collective treasury acceptance runbook

This is the deployment and acceptance checklist for the shared AAE wallet. It deliberately does not create credentials, provision a wallet, fund an address, or broadcast a transaction from a developer workstation.

## Fixed product rules

- One shared CDP EVM wallet for every agent on the configured network/asset.
- Initial USDC holding cap: 500 USDC total across the shared wallet.
- No per-agent lifetime earning ceiling.
- The owner alone may increase the wallet cap through the authenticated owner control plane; each increase is audited. No automatic growth formula is configured.
- Owner receives 50% of net profit as a separate accounting allocation.
- Any unallocated suspense balance above the shared-wallet cap is swept to the configured owner address. This is not the 50% profit share and must never be counted twice.
- Mainnet remains disabled until the full testnet acceptance and operational review are signed off.

## Deployment prerequisites

1. Install the project and CDP extra in the isolated deployment environment:
   `pip install '.[cdp]'`.
2. In CDP, create a dedicated project/API key and a restrictive EVM account policy. Restrict network to Base Sepolia, token to the selected Base Sepolia USDC contract, destinations to the approved test destinations, and amounts/rates to test limits. Review the policy in CDP; a policy ID alone is not evidence that its rules are safe.
3. Supply `CDP_API_KEY_ID`, `CDP_API_KEY_SECRET`, `CDP_WALLET_SECRET`, and `AAE_CDP_ACCOUNT_POLICY_ID` through the deployment secret manager only. Never commit them, paste them into chat, or expose them to agent prompts.
4. Configure `AAE_OWNER_PRINCIPAL_ID` from the authenticated control-plane identity. Configure the owner's public testnet receiving address through `configure_owner_payout_address()`; do not accept an address supplied by an agent.
5. Configure `AAE_EVM_RPC_URLS` with at least two independently operated Base Sepolia RPC endpoints. Ensure the receipt monitor and outgoing-transfer verifier use independent sources and validate exact chain, token contract, sender, receiver, amount, block canonicality and finality.
6. Fund the test wallet only with testnet USDC and enough Base Sepolia ETH for gas. Verify the wallet address in CDP and a Base Sepolia block explorer before funding.

## Provision or recover the testnet wallet

Run from the deployed application environment after the policy and secrets are configured:

```bash
economy-treasury --network base-sepolia
```

The command is idempotent around the stable CDP account name `AAE_MASTER_TREASURY`. It registers the public address in `data/collective_treasury.sqlite3` and reports `funds_moved: false`. Confirm that all agents resolve to this same address.

The CLI does not configure the owner payout address, create payment intents, fund the wallet, or start the accounting runtime. Those are separate owner/control-plane and deployment operations.

## Read-only balance gate

Set the token contract to the actual test USDC contract selected for this CDP project and run:

```bash
economy-treasury-reconcile \
  --network base-sepolia \
  --chain-id 84532 \
  --asset USDC \
  --token-contract "$BASE_SEPOLIA_USDC_CONTRACT" \
  --minimum-native-balance-wei 1000000000000000
```

The command must pass against two independent RPC operators before any worker is enabled. It is read-only and must not be treated as a transaction inventory; inspect CDP and chain history for any wallet-originated transaction not represented in AAE's ledger.

## End-to-end acceptance sequence

Run this on testnet with test amounts and retain the transaction hashes, provider evidence, ledger snapshots and runtime logs as an acceptance record.

1. **Shared address:** provision/recover the CDP account; confirm every configured agent receives exactly the same public address and no agent API exposes signing credentials.
2. **Receive and attribute:** create a trusted payment intent for a test agent with exact amount and payer binding; send a test USDC transfer; verify the finalized transfer is attributed once to that agent. Replay the same event and confirm no duplicate credit.
3. **Suspense:** send a separate unrecognized test deposit; confirm it is credited only to `treasury:unallocated`, not guessed to an agent.
4. **Agent spend:** request a spend within the agent's virtual balance, destination allowlist, per-transaction and daily limits. Confirm exactly one transfer is broadcast from the shared address and only exact finalized independent evidence settles it.
5. **Uncertain recovery:** simulate a provider timeout after submission. Confirm the reservation remains uncertain, no retry broadcasts, and reconciliation settles only after discovering and verifying the original transaction.
6. **Gas and profit close:** record the finalized Base execution/L1/blob gas fee and a timestamped trusted USDC valuation. Close the test accounting period; verify gas is included in expenses and owner allocation is exactly 50% of net profit (after configured operating reserves/expenses).
7. **Overflow:** cause a controlled testnet unsolicited deposit above the $500 cap. Confirm agent spending is blocked, only unallocated suspense excess is reserved for the owner, the exact transfer is independently verified, and the pool returns to or below the cap. Confirm the overflow amount is not added to the 50% net-profit payout.
8. **Reorg and quorum gates:** inject provider disagreement and a simulated non-canonical/reorged receipt in the test harness. Confirm the runtime blocks owner and agent transfers until the quorum and reorg guard are healthy.
9. **Runtime order:** confirm logs show receipt intake → reorg scan → independent balance reconciliation → owner overflow/profit work (if due) → fresh balance reconciliation after owner transfers → agent spending. Any failed gate must block later actions.
10. **Recovery and audit:** restart the runtime during an uncertain transfer and confirm it reconciles without rebroadcast. Verify cap changes, payout-address changes, reservations, transfers and owner allocations have durable audit records.

## Accounting runtime callback contract

The runtime treats owner payout callbacks as authorization gates, not informational hooks. A callback must return a dictionary with an explicit success status; a missing, malformed, failed, pending, blocked, uncertain, or unknown status stops the cycle before agent spending.

- The overflow callback must return `status=settled` or `status=not_needed`. If present, `uncertain` and `skipped` counts must both be zero. A `pending` result is not success, even if a separate capacity read appears below the cap.
- The owner-profit callback must return `status=completed`, `paid`, `no_distribution`, or `not_needed`. If present, `uncertain`, `pending`, `blocked`, and `failed` counts must all be zero.
- Use `CollectiveOwnerProfitPayoutWorker.runtime_callback(network=..., asset=...)` as the Accounting runtime callback. This worker uses `CollectiveTreasuryStore.treasury_period_closes` and `treasury_owner_profit_payouts`, so the 50% owner share is paid from the same shared wallet and internal owner sub-ledger as the agents. It does not use the legacy `AgentFinanceStore` per-agent wallet ledger. It re-reads the durable unsettled-close queue after each bounded batch (one row beyond the batch limit) and reports `pending`, not `completed`, if any obligation remains. Uncertain transfers are reconciled by hash without rebroadcasting; missing owner configuration, malformed state, blocked results, or a detected backlog produce a non-success status. A successful callback is still followed by independent physical balance reconciliation.
- Supply `QuorumEVMVerifier` as the payout verifier. Its async `verify_transfer()` checks an exact successful ERC-20 receipt against a strict majority of distinct RPC providers; each `EVMJSONRPCSource.verify_transfer()` validates the transaction hash, token contract, source, destination, exact atomic amount, canonical block hash, and finalized height. Provider disagreement or insufficient finality leaves the payout uncertain and blocks agent spending.
- A successful callback is followed by an independent physical balance reconciliation before agent spending. Callback success alone is never proof that a transfer settled.

Keep these contracts covered by tests whenever callback adapters or payout workers change.

## Acceptance decision

Do not enable Base mainnet merely because unit tests pass. Require all of the following:

- All GitHub Actions checks pass on the exact proposed commit.
- The above Base Sepolia sequence passes with retained independent chain evidence.
- CDP account policy and owner payout destination receive a separate security review.
- RPC operators are genuinely independent and their trust/availability assumptions are documented.
- The complete wallet transaction inventory, native ETH gas funding, gas valuation source, backups, pause controls, incident response and recovery procedure are reviewed.
- Mainnet is enabled only by a separately reviewed deployment change. The explicit CLI flag `--confirm-mainnet` is a final guard, not a substitute for this review.

## Pending receipt pages and cursor safety

The receipt monitor deliberately holds its durable provider cursor whenever a fetched page contains at least one non-finalized transfer. It re-fetches that same page on later cycles until every observation on it is finalized or otherwise safely handled. This prevents a provider with an exclusive `after-cursor` API from making a still-pending deposit disappear permanently after the cursor moves past it. Replayed finalized receipts are idempotent.

This is a deliberate safety-over-throughput tradeoff: one transfer that remains pending indefinitely can hold up later receipt pages from that provider. The Accounting runtime should expose and alert on repeated `cursor_held=true` cycles and the age of the oldest pending observation. Operators must investigate provider finality, transaction replacement, and chain canonicality; they must not manually advance the cursor to clear a backlog. If a provider offers a separately queryable pending-event feed or inclusive block-range replay, a future adapter may use that capability to avoid head-of-line blocking while preserving durable recovery. Any such change must retain a regression test proving that a deposit which finalizes after the initial observation is still ingested exactly once.

## Current repository boundary

Unit and integration tests use controlled fixtures; they do not prove that a real CDP wallet has been provisioned or that real Base Sepolia transactions have settled. A deployment operator must execute this runbook in the protected environment. No private keys or secret values should ever be sent to the assistant.
