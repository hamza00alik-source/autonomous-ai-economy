# BasedAgents live opportunity and payment screening — 2026-11-18

This is a dated, read-only snapshot. It does not authorize registration, wallet setup, claiming, delivery, or payment.

## API contract checked

- Open tasks: `GET /v1/tasks?status=open&limit=100`
- Task detail: `GET /v1/tasks/{task_id}`
- Payment audit: `GET /v1/tasks/{task_id}/payment`
- Escrow configuration: `GET /.well-known/x402`
- Settled work: `GET /v1/tasks/settled`

The current task shape contains nested bounty fields (`amount_atomic`, `amount_display`, `token`, `network`), explicit boolean `claimable`, payment fields (`payment_status`, `payment_verified`, `payment_tx_hash`), and an `escrow` object. Task detail also includes a payment summary; the separate payment endpoint returns payment state, requirements, and audit events.

The public x402 discovery endpoint reported payments enabled, escrow enabled, USDC on Base mainnet, and a 0.10 USDC minimum. These global settings do not prove any particular task is funded.

## Live open-task screening

A read-only request to the open-task API returned 12 open tasks. All 12 were posted by the same publisher, Industrial Sentinel Acquisition:
- 5 Revenue Guard tasks: 0.25 USDC each, requiring an authorized external runtime, Docker, wallet monitoring, x402 activity, and at least 0.50 USDC settled platform revenue across two UTC days plus a real paid Sentinel cycle on day two.
- 5 Revenue Cashback tasks: 2.00 USDC each, requiring the same external Sentinel installation to generate at least 2.50 USDC settled platform revenue across two UTC days and a real paid cycle on day two.
- 2 Revenue Trial tasks: no guaranteed bounty; optional rebate only after at least 10 USDC of settled platform revenue and additional operational conditions.

The inspected task records showed `payment_status: pending`, `payment_verified: 0`, `payment_settled: 0`, `payment_tx_hash: null`, and `escrow: null`.

**Decision: reject all 12.** They are incompatible with the current no-budget/no-external-runtime setup. The displayed rewards are conditional, not guaranteed earnings. No task was claimed and no external commitment was made.

## Settled payment evidence

The public settled endpoint reported:
- 79 settled tasks all-time
- 43.70 USDC paid all-time
- 8 settled tasks in the trailing 30-day sample
- Median task-creation-to-payment time: 1,160,694 seconds (about 13.4 days)
- Median claim-to-delivery time: 484 seconds (about 8.1 minutes)
- Median review time: 604,926 seconds (about 7.0 days)

The sampled settled records include Base explorer links. This confirms the marketplace has recorded real payments, but does not predict that this project will win a task or receive payment.

## Implementation changes

- Normalize current nested and legacy bounty fields.
- Fail closed when `claimable` is absent or not explicitly true.
- Preserve the task-detail payment summary and add a separate read-only payment-audit reader.
- Require an escrow object with `status: funded`, registry payment verification, a valid deposit transaction hash, and a separate independent chain-verification result before local claim readiness can be shown.
- Keep `claim_allowed = false` unconditionally. No marketplace write operation is implemented here.

## Remaining gate

A real independent Base-chain verifier must validate the deposit transaction against the current escrow wallet, USDC contract, chain ID, amount, and task-specific evidence. Registry fields alone are not independent chain verification. Agent registration, payout-wallet proof, claim, delivery, and settlement remain separate owner-approved steps.
