# AAE collective treasury (single on-chain wallet)

## Decision

AAE uses **Option A**: one shared on-chain treasury wallet for each configured network/asset pair, with separate virtual balances for each agent in AAE's accounting ledger. For the first deployment, the intended asset is USDC on Base. Agents do not receive individual blockchain wallets and do not hold private keys.

The current provider adapter is Coinbase Developer Platform (CDP) Server Wallets. CDP manages the EVM account and signing infrastructure; AAE stores only the provider account reference and public address. CDP's Python SDK supports server-managed EVM accounts, account policies and USDC transfers on Base/Base Sepolia. The optional dependency is installed with `pip install '.[cdp]'`.

## What was added

- `src/economy/collective_treasury.py`
  - A single registered treasury address per network/asset; attempts to replace it are rejected.
  - Agent virtual accounts, daily and per-transaction budgets, destination allowlists and emergency pause.
  - Double-entry-style virtual balance attribution for incoming receipts, suspense/unallocated deposits, expenses, master share and operating reserves.
  - Idempotent receipt identity using network + transaction hash + transfer/log reference.
  - Payment-attribution reference matching before an unallocated receipt can be assigned to an agent.
  - Spend reservation before signing; exact source, destination, asset and amount must match independently verified settlement.
  - Ambiguous broadcast outcomes are held as `uncertain`; they cannot be cancelled or blindly retried.
  - Period close calculates net realized profit, reserves and owner share, then moves virtual ledger balances.
- `CDPServerTreasuryWallet`
  - Reuses one stable named CDP EVM account, binds the required restrictive CDP account policy, and returns its public address.
  - Sends USDC from the shared account using CDP's server-managed signer.
  - Never reads, exports or stores private keys.
- `economy-treasury` CLI provisions/retrieves and registers the one shared wallet.
- `tests/test_collective_treasury.py` covers shared-wallet uniqueness, suspense attribution, receipt deduplication, virtual spend controls, settlement checks, emergency pause, profit allocation and the CDP adapter boundary.

## Why attribution is mandatory

An ERC-20 USDC transfer to one common address does not contain a free-form agent identifier. The destination alone cannot tell AAE whether Agent A, Agent B or another agent earned the money.

AAE therefore records incoming transfers in one of two ways:

1. The trusted payment integration supplies a verified payment-intent attribution and the chain monitor verifies the exact settled transfer; AAE credits that agent's virtual account.
2. If no trusted match exists, AAE credits `treasury:unallocated`. The Accounting Agent may assign it only after matching the stored attribution reference to a verified payment intent. An unknown deposit is never guessed or silently credited.

For machine-to-machine service payments, integrate a payment-intent layer (for example x402) that binds the request, payer, intended agent, amount, asset and destination before settlement. The protocol/payment adapter must independently verify the settled transfer before it supplies attribution to this ledger.

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
- An agent may request a spend without asking the owner for every routine transaction. AAE checks its virtual balance, budget, destination allowlist and pause status. The external CDP account policy must independently constrain the signing account.
- A spend is not an expense until the chain verifier confirms the exact transaction and finality. Broadcast timeouts are ambiguous and must be reconciled before any retry.
- The treasury's on-chain balance is the actual pooled asset balance. Virtual agent balances are internal accounting claims against that pool, not separate segregated assets or legal ownership rights.
- Never allow the sum of virtual liabilities, reserves and pending obligations to exceed reconciled treasury assets. Add a periodic full-balance reconciliation and alerting before production operation.
- A common wallet creates commingling and concentration risk. Use strict policies, independent transaction monitoring, a master emergency pause, protected database backups, dual control for policy/address changes, and a documented recovery process.
- The first implementation provides the core ledger and CDP wallet provisioning/transfer adapter. It does **not** yet wire the live chain monitor's incoming transfer attribution to payment intents, create customer invoices, run a continuous accounting agent, automatically execute queued spends, or perform an always-on balance reconciliation daemon.

## Important provider limitation

The CDP transfer SDK call does not expose an AAE idempotency key in this adapter. If a transfer request times out after submission, the caller must search/reconcile the provider and chain state before retrying. The AAE spend reservation can be held in `uncertain` state for that purpose. Do not build blind automatic retries around an ambiguous transfer.

## Sources

- Coinbase CDP Python SDK: https://coinbase.github.io/cdp-sdk/python/
- CDP Wallet API quickstart: https://docs.cdp.coinbase.com/wallet-api/docs/quickstart
- CDP SDK source: https://github.com/coinbase/cdp-sdk
