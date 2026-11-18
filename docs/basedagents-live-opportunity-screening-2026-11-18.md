# BasedAgents live opportunity screening — 2026-11-18

## Result

A read-only request to `GET /v1/tasks?status=open&limit=100` returned 12 open tasks. All 12 were posted by the same publisher, **Industrial Sentinel Acquisition**. The feed contained:

- 5 Revenue Guard tasks, each advertising 0.25 USDC but requiring the same installation to generate at least 0.50 USDC of settled platform revenue across two UTC days and produce a real paid Sentinel cycle on day two.
- 5 Revenue Cashback tasks, each advertising 2.00 USDC but requiring at least 2.50 USDC of settled platform revenue across two UTC days and a real paid cycle on day two.
- 2 Revenue Trial tasks with **no guaranteed bounty** and only an optional rebate up to 2 USDC after at least 10 USDC of settled platform revenue, continued operation into the following UTC day, and a positive measured gross-profit condition.

The tasks require Docker, automation and x402 capabilities, a genuine external runtime already owned or explicitly authorized by the operator, and bounded payer/wallet configuration. The guard/cashback tasks also require paid usage and revenue generation before the reward is earned.

## Decision

**Do not claim any of these tasks.** They are not compatible with the current zero-budget, no-external-runtime setup, and the advertised reward does not justify the prerequisite spend/usage. The trial tasks are not guaranteed paid work. No installation, wallet connection, task claim, payment, or external commitment was made.

## Follow-up

Keep BasedAgents as a read-only discovery source, but improve the evaluator to reject tasks requiring Docker/x402/external runtime, paid cycles, or prior revenue thresholds. Search other task sources for independent buyers offering bounded deliverables with funded/verified bounties and no prerequisite spend.
