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
The additive D1 schema is provisioned in production. GitHub integration remains on draft PR #41; the production Worker has not yet been updated. No marketplace jobs have been inserted and no AI draft generation has been run by this lane.
