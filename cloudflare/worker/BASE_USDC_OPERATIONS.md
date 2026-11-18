# Base USDC Operations Runbook

This runbook is for an operator responsible for the private Base USDC checkout/indexer. It does not authorize production activation, key creation, contract deployment, wallet signing, fund movement, or legal compliance decisions.

## Current operational state

- Checkout, indexer and legal/crypto approval gates must remain explicitly disabled until each prerequisite is independently approved.
- The indexer has a persistent fail-closed incident latch. A checkpoint hash mismatch halts scanning; there is no automatic unhalt.
- A healthy private `/v1/status` response is an observation, not proof of a live payment or permission to enable checkout.
- Worker error logs are not external paging. No external alert destination is currently configured.
- Test fixtures, mocked RPC and fake D1 do not constitute a production rehearsal.

## Routine health review

1. Authenticate to the private status endpoint using the approved operator credential. Never put bearer tokens in tickets, screenshots, chat, URLs, or logs.
2. Confirm the indexer state is `running`, the checkpoint height advances across scheduled executions, and the last update time is recent relative to the five-minute schedule.
3. Confirm the incident latch fields are empty and no manual-review flag is raised.
4. Review Worker logs for RPC errors, repeated retries, unexpected exceptions, quarantined events, and any incident-latch message.
5. Compare the reported state with the D1 operational ledger using an approved read-only procedure. Do not edit ledger rows to make status appear healthy.
6. Record the review time, operator, observed state and any incident reference in the private operations record. Do not include secrets or buyer credentials.

A missing status response, stale checkpoint, missing indexer-state row, RPC/configuration failure, or inconsistent ledger is not healthy. Treat it as an incident and keep checkout disabled.

## Reorg or persistent-halt response

When the indexer reports `halted` or logs a checkpoint hash mismatch:

1. Do not restart, redeploy, toggle gates, delete the latch, move the cursor, or attempt an automatic rewind.
2. Keep public checkout disabled. The application should hide the storefront and reject new invoice creation while the state is missing or halted.
3. Treat every previously settled invoice as requiring review. The halt handler revokes download entitlements and moves affected revenue attribution into refund review; do not manually restore access or mark revenue payable.
4. Preserve the cursor, checkpoint values, halt timestamp/reason, Worker logs, transaction hashes, block numbers and relevant RPC responses for forensic review.
5. Capture independent canonical-chain evidence from more than one trusted Base RPC source where available. Record the chain ID, contract address, block number/hash, transaction hash, log index, receipt status and confirmation depth. Do not trust buyer-submitted screenshots or transaction hashes as settlement proof.
6. Reconcile every affected invoice and payment event against canonical chain history and the D1 ledger. Identify duplicate events, missing logs, changed block hashes, wrong contract/token/merchant, amount mismatches and any entitlement previously delivered.
7. Escalate unresolved discrepancies to the contract/security reviewer and the designated legal/compliance contact. If funds may have been misdirected or a key may be compromised, follow the incident response process for the relevant provider/wallet; never request a seed phrase or private key.
8. Keep the incident open until a named operator has documented the reconciliation, independently reviewed the proposed recovery, and obtained the required approval for any state-changing recovery action.

## Recovery gate (manual only)

There is intentionally no self-service or automatic unhalt procedure. Before any recovery change is considered, require all of the following:

- Root cause and affected block range documented with independent canonical evidence.
- All affected invoices, events, download entitlements and revenue rows reconciled.
- Refund/compensation decisions separately reviewed; no automatic agent payout is inferred from gross revenue attribution.
- Database backup/export and a rollback/recovery plan reviewed.
- The exact proposed state change and its impact reviewed by a second qualified operator.
- Explicit authorization from the system owner for that specific recovery action.
- A post-recovery read-only verification plan and incident record prepared.

Do not improvise SQL, manually clear `halted_at`, advance the cursor, or restore downloads. Recovery implementation must be reviewed against the deployed schema and code version first.

## External alerting requirements

External paging is not implemented. Before relying on this system for real customers, select an approved alert destination and implement a separate, authenticated, rate-limited notification path. At minimum, alert on:

- Persistent indexer halt or checkpoint mismatch.
- Indexer checkpoint stale beyond an explicitly chosen threshold.
- Missing or unhealthy D1 indexer state.
- Repeated Base RPC failures or scan errors.
- Quarantined payment events and settlement mismatches.
- Checkout gate unexpectedly enabled while legal/security prerequisites are not recorded.

Alerts should contain only a non-sensitive incident ID, category, timestamp and private status reference. Never include buyer access tokens, bearer credentials, signer material, wallet secrets or full payment payloads. Alert delivery failure must not clear or weaken the incident latch. Test notification delivery with synthetic events before production use.

## Production activation checklist

Production activation is a separate approval process and is not authorized by this document. It requires, at minimum:

- Independent smart-contract security review and approved deployment.
- Verified contract address, chain ID, immutable merchant, signer and native USDC token.
- Dedicated invoice signer provisioned through an approved secret-management process; never use the merchant wallet key.
- Qualified Pakistan legal advice or written PVARA clarification for the exact merchant flow, plus any required licensing/compliance approvals.
- Live Base RPC and D1 rehearsal, including settlement, duplicate handling, underpayment/mismatch quarantine, download expiry and reorg-halt recovery.
- External monitoring and alert delivery tested.
- Backup, incident ownership, support/refund and key-rotation procedures documented.
- Explicit owner approval for each relevant gate and for public checkout activation.

Until these conditions are met, keep public checkout, deployment, publication, payouts and fund movement disabled. Do not describe CI success or mocked tests as production readiness or revenue.


## Base Sepolia rehearsal (test tokens only)

The code supports a separate Base Sepolia indexer configuration for controlled testing. It must use a dedicated test-only deployment, database and invoice-signing key.

1. Confirm the Circle-published Base Sepolia USDC address from https://developers.circle.com/stablecoins/usdc-contract-addresses. The expected token is `0x036CbD53842c5426634e7929541eC2318f3dCF7e` on chain ID `84532`.
2. Obtain test ETH and test USDC only from reputable testnet faucets; Circle documents USDC distribution at https://faucet.circle.com. Test tokens have no financial value.
3. Deploy only the dedicated `BaseUsdcDirectCheckoutSepolia` contract to Base Sepolia after a separately approved testnet deployment action. Record the exact deployed address and block number.
4. Configure the test worker/indexer with `BASE_CHAIN_ID=84532`, `BASE_USDC_TOKEN_ADDRESS=0x036CbD53842c5426634e7929541eC2318f3dCF7e`, the Base Sepolia HTTPS RPC, the test contract address, and its deployment block. Use a separate D1 database and a test-only invoice signer.
5. Verify the EIP-712 signature domain is chain 84532 and the deployed test contract; verify token, merchant, amount, order ID, receipt and canonical block before considering the synthetic order settled.
6. Exercise duplicate event delivery, wrong-token and wrong-amount quarantine, expired invoice, insufficient confirmations, cursor mismatch, entitlement revocation and manual recovery using test data.
7. Confirm the Base-mainnet checkout route still returns unavailable when `BASE_CHAIN_ID=84532`. Never point the testnet worker at production D1 or production signer material.

No testnet contract has been deployed and no wallet transaction has been submitted. The CI suite is a local deterministic simulation, not a live Base Sepolia rehearsal.


## Provisioned Base Sepolia test ledger

A dedicated Cloudflare D1 database named `aae-base-sepolia-test` has been provisioned for testnet-only integration. It is separate from the production/private `aae-private-ai-economy` database.

- The Base USDC invoice, payment-event, indexer-state, quarantine and agent-revenue tables were created in the test database.
- The indexer incident-latch columns (`halted_at`, `halt_reason`) were applied.
- The payment-event chain constraint permits only Base mainnet (8453) and Base Sepolia (84532); a direct schema test accepted 84532 and rejected chain ID 1.
- No production database was modified by this provisioning step.
- No testnet deployment block or contract address is recorded yet, so the indexer cursor has intentionally not been initialized and scanning is not enabled.
- The test database has no live Worker binding yet. Do not bind it to the production Worker or activate scheduled scanning until a separately deployed test Worker has been reviewed and its test-only configuration is complete.

This database provisioning and schema validation are not a live payment test. A separately controlled deployer, dedicated test invoice signer, funded buyer wallet, test USDC, and explicit wallet transaction are still required for an on-chain purchase and download rehearsal.
