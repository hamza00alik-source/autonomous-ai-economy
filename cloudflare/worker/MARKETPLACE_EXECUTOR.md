# Private marketplace execution lane

This Cloudflare Worker lane connects the existing read-only SwarmMemo and Taskmarket scanners to a private AI draft queue.

## Flow
1. The existing cron polls both marketplaces and verifies source-specific eligibility/escrow information.
2. `marketplace_queue.js` normalizes the discovered records, applies a second risk screen, and inserts each source/task pair once into D1.
3. Ineligible, simulated, and credit-only work is blocked. SwarmMemo rewards with `unit: "credit"` are explicitly treated as non-cash.
4. New jobs remain queued with `owner_approved=0`. The scheduled worker will not invoke the AI model for them.
5. An owner-approved queued job may be processed into a private draft. At most one approved job is processed per cron cycle.
6. Drafts and errors are persisted in `aae_execution_jobs` and can be inspected through the authenticated queue endpoint.

## Approval and cost boundary
- The queue inspection route is `GET /v1/marketplace/execution-jobs`.
- Per-job approval route is `POST /v1/marketplace/execution-jobs/{job_id}/approve`.
- Both routes use the Worker’s existing bearer-token authorization.
- Approval authorizes private AI draft generation only. It does not authorize a marketplace claim, external submission, publication, messaging, signature, transfer, or spending.
- This gate prevents unattended metered model calls. Approve only after reviewing the task and its reward/terms.

## Safety boundary
- Marketplace discovery remains read-only.
- The executor never claims tasks, submits work, posts, publishes, messages, promotes, spends, signs transactions, or transfers funds.
- Risk screening blocks stakes/deposits, wallet/transaction signing, marketing/publication, medical/legal/financial advice, malware/exploits, human-experience claims, simulated work, and credit-only rewards.
- Screening is heuristic, not a guarantee that a task is safe or that a draft will be accepted. Every deliverable requires review.

## Files
- `src/marketplace_executor.js`: task screening and private draft generation.
- `src/marketplace_queue.js`: D1 deduplication, queueing, owner approval gate, and draft persistence.
- `migrations/0007_marketplace_execution_jobs.sql`: execution job table.
- `migrations/0008_marketplace_execution_approval.sql`: explicit owner approval column.
- `test/marketplace_executor.test.js` and `test/marketplace_queue.test.js`: unit and integration coverage.

## Deployment status
The implementation is merged into `main` via PR #41. Production D1 schema is provisioned. Worker version `15` (`35da2e85-7f35-4dc8-bae4-4434a8683b84`) is deployed at 100% through deployment `79105284-e4bf-4d45-8fdb-03a9d928e80c`; existing secret bindings, AI, D1, rate limit, static assets, and the `*/5 * * * *` cron schedule were verified after deployment. The deployed script source was read back and confirmed to include the queue import, approval route, cron intake, and owner-approval gate. At the last D1 check, the execution queue still had zero rows; no AI draft generation, task claim, or submission has occurred.


## External cash-bounty discovery
- A read-only connector polls the public Agent Bounty Feed `/earn-now` endpoint every five minutes.
- Fresh items with at least $1 USD-equivalent, a supported source currency (or explicitly labeled `USD_EQUIVALENT` when the feed omits currency), a valid HTTPS source URL, and an unexpired deadline are stored in `aae_external_bounty_discoveries`. The aggregator's `est_usd` is an estimate, not proof of the exact payout token or amount.
- The scanner rejects feed data older than six hours and items requiring KYC, stake, bond, purchase, or human-only participation.
- Wallet requirements such as `wallet_evm` are recorded for human review; they do not authorize signing or spending.
- Inspect candidates at authenticated `GET /v1/marketplace/discovered-bounties`.
- Discovery candidates are separate from the execution queue. They are not automatically sent to AI, claimed, or submitted.
- The source feed is a third-party aggregator. Its own verification and reward estimates are leads, not payment guarantees; re-check the original bounty's terms, remaining slots, deadlines, and payout before work.


## Bounty feed diagnostics and safety filters
- Production Worker version 17 adds authenticated `GET /v1/marketplace/bounty-feed-runs` to show recent successful, skipped, or failed feed sync attempts, counts, feed timestamp and bounded error text.
- Feed runs are recorded in `aae_external_bounty_feed_runs`; the table was applied to production before deployment.
- The scanner rejects first-timer-only requirements and social-media engagement/promotion tasks in addition to KYC, stake, bond, purchase and human-only prerequisites.
- Previously stored social/first-timer candidates were removed from the production discovery table.
- The feed discovery table currently retains only the ElgoraHub security bounty lead. It requires an EVM wallet and a Foundry security proof; it is not automatically eligible for execution and is not a guaranteed payment.


## Jobbi USDC discovery
- The public Jobbi JSON Feed is polled read-only alongside the existing marketplace sources.
- Only agent-lane tasks with claims open, escrowed USDC-on-Base rewards of at least 1 USDC, a payout grade A/A-/B+/B, and a source update within seven days are retained.
- Listings requiring social promotion, claim bonds, staking, deposits, purchases, child-bounty funding, first-timer-only eligibility, or Mac-only environments are rejected.
- Review candidates at authenticated `GET /v1/marketplace/jobbi-discoveries`.
- Jobbi is an index, not the payer. Verify each original board's live terms and payout eligibility before any work or claim. USDC payout still requires a Base wallet; this scanner does not create one or sign anything.


## Frantic USDC-on-Base discovery
- The public Frantic board is polled read-only.
- Candidates are limited to funded tasks priced $1-$10, with an apparent open slot and a technical/data/PR deliverable.
- The scanner excludes social posting, external citations, outreach, promotion, funding, deposits, bonds and staking.
- Because the board projection can be stale, every candidate is re-fetched from its individual bounty endpoint. It is stored only if the detail response confirms funded status and at least one available claim slot.
- Review candidates at authenticated `GET /v1/marketplace/frantic-discoveries`.
- Official Frantic rules specify USDC payouts on Base. A Base wallet and verified contact identity are required before payment/claim; this scanner does not register an agent, set a wallet, claim, or submit work.


## Live discovery checkpoint — 2026-11-21
- Production cron is still scheduled every five minutes. The latest observed scanner run (05:15:40 UTC) completed without feed errors.
- Agent Bounty Feed: 1 candidate stored; 2 rejected.
- Jobbi: 100 feed entries examined, 0 retained. The observed entries are BountyBook tasks with x402 payout, `promised` rather than escrowed payment, and `C-` payout grade; the strict filter correctly excludes them.
- Frantic: 0 candidates retained in the latest observed run (1 rejected). The public board includes tasks requiring public Reddit posting or external editorial outreach; these remain outside the no-social-promotion policy.
- ElgoraHub bounty #3 is a verified open 36 USDC escrow lead with 7/10 submission slots used and a 2026-11-21 23:59 UTC deadline. It requires a local Foundry proof of a qualifying smart-contract vulnerability, an EVM wallet and native Base gas for the submission transaction. It is not a beginner task and not suitable for automatic claim/submission; no wallet action has been taken.
- ElgoraHub bounties #4 (20 USDC) and #5 (25 USDC) already have 10/10 submission slots used. They are not available to new Solvers.
- Current AAE earnings remain $0.00. No task has been claimed or submitted; no execution job has been approved.
- GitHub Actions for the Jobbi discovery PR passed 69/69 tests. Production D1 migration for Jobbi discoveries is applied and the Jobbi scanner is live.


## Direct Elgora discovery
- PR #46 merged after GitHub Actions passed 77/77 tests.
- Production Worker version 20 is deployed at 100%; the existing five-minute cron and all prior bindings/secrets/assets are preserved.
- Added a read-only poll of Elgora's public open-bounty API. It retains Base mainnet listings only when the escrow token is the official Base USDC contract, escrow is at least 1 USDC, the deadline is in the future, and fewer than 10 submissions are recorded.
- The 10-submission limit is the default-cap assumption; the worker records this explicitly and requires a separate on-chain guard-override check before any future submission.
- No wallet, claim, submission, signature, transfer, or spend is performed by this scanner.


## Direct Elgora scanner hardening
- PR #47 merged after GitHub Actions passed 77/77 tests.
- Worker version 21 is deployed at 100%; the existing five-minute schedule and all secret, D1, AI, assets and rate-limit bindings remain present.
- Direct Elgora API discoveries now use the `elgora-api:` ID namespace, separate from third-party aggregator records, preventing concurrent D1 upserts from overwriting one another.
- The previous observed direct scan found bounty #3 only (36 USDC escrow, 7 submissions, estimated 3 remaining slots); the two other open Elgora bounties were full at 10/10. The next scheduled scan after version 21 is required to verify the namespace fix in live D1 data.


## Multi-rail digital payout discovery — 2026-11-22
- Jobbi discovery now reads the unfiltered agent lane once per hour (Jobbi documents hourly refresh and asks clients not to poll more often).
- Priority order: escrowed USDC on Base; other explicitly named USDC/USDT networks; explicitly named ETH/BTC/SOL wallet rails; then Payoneer and Wise digital payout rails.
- Payoneer is marked supported in Pakistan. Wise is retained only with an account-availability confirmation flag. Wallet rails require the exact asset and network; ambiguous `wallet`, generic `x402`, unknown rails and unpriced platform tokens are rejected.
- Each record stores the native reward amount, optional USD estimate, network, payout-region status, and payout priority. Native token amounts are never mislabeled as USD.
- Listings must still report open claims, escrowed payment, a B-or-better payout grade, a future deadline, explicit acceptance criteria, and a recent modification. Social posting, outreach, bonds, stakes, deposits, paid APIs/subscriptions, third-party installation, personal-data handling, and legal/financial commitments are rejected.
- Jobbi is an index only. A listing is not treated as independently board-verified; original board status and payout terms must be checked again before owner approval. The worker never registers accounts, claims, bids, submits, signs, publishes, or transfers funds.
