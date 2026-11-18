# Taskmarket Base live opportunity screening — 2026-11-18

## Scope

Read-only inspection of the public Taskmarket Base mainnet API:
- `GET /api/tasks?chainId=8453&status=open&limit=100`
- Individual task detail reads for the relevant task IDs
- Read-only BaseScan transaction receipt/event-log inspection

No identity registration, wallet connection, signature, claim, submission, social post, purchase, or payment was performed.

## Live feed result

The API returned three open Base tasks with `hasMore=false`.

| Task | Advertised pool / escrow | Competition | Decision |
|---|---:|---:|---|
| Sera survey, `TSK-KR95B88S` | 9 USDC | 80 submissions; pool split equally among up to 9 accepted passes | Reject: split reward and very crowded |
| FlapJax audit, `TSK-B0QVNCPG` | 1 USDC listing deposit | 13 submissions; actual worker payout is 100,000 FLAPJAX on BSC, paid off-platform | Reject: listing deposit is not worker payout; external token and wallet/age eligibility |
| Lumen House promotion, `TSK-EWJ9R6Z2` | 5 USDC | 52 submissions; first 50 qualifying agents share pool | Reject: public promotional reply required; split reward and crowded |

## Independent escrow receipt checks

BaseScan displayed successful transactions to the Taskmarket Base contract and the matching `EscrowFunded` event with the expected task ID and amount:

- Sera: [BaseScan receipt](https://basescan.org/tx/0x73f1d8ba99e67074b2b3b42826a4eeb2bf7272e3e915c66cb627b7482c5f4f62) — successful receipt, `EscrowFunded` amount 9,000,000 base units (9 USDC)
- FlapJax: [BaseScan receipt](https://basescan.org/tx/0x8453f71323747ddcd7d509cb9ed701e04192aac149dbefeeaf697352c42183d2) — successful receipt, `EscrowFunded` amount 1,000,000 base units (1 USDC); task description says this is a listing deposit, not the per-worker payout
- Lumen House: [BaseScan receipt](https://basescan.org/tx/0xecbebb3b19507dbc531f505bf4f6468623ed0a6528675a9ea3aa79427c99b68d) — successful receipt, `EscrowFunded` amount 5,000,000 base units (5 USDC)

These checks prove the listed escrow funding event for each task at the time inspected. They do **not** prove the requester will accept any particular worker submission or that a worker has earned or withdrawn money.

## Implementation decision

The adapter independently verifies receipts using the public Base JSON-RPC endpoint. It requires:
- a successful transaction receipt;
- an `EscrowFunded` event emitted by the Taskmarket Base contract;
- the exact task ID in the event;
- the expected reward amount and principal component.

The evaluator additionally rejects split pools, promotional replies, off-platform/token payouts, worker deposits, unsupported task modes, excessive competition, short/unclear scopes, and rewards below the configured threshold. A task can only reach `qualified_for_local_draft`; that state never permits registration, wallet signing, claiming, or submission.

## Result

No suitable task among the three currently returned listings. No task claimed. No revenue earned. No money spent.
