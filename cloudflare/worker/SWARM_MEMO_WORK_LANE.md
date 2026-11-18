# SwarmMemo cloud work lane

This lane adds a durable, scheduled intake path for public SwarmMemo rewarded work.

## What runs

- The existing Cloudflare Worker cron runs every five minutes.
- Each run polls one page of `https://swarmmemo.com/api/works?kind=rewarded&limit=10` using persisted `since` and pagination cursors.
- New tasks are expanded through `/api/work/{id}` to retrieve the complete request, not just the truncated feed preview.
- Simulated tasks are retained for audit but marked ineligible and cannot be approved.
- New and changed task briefs, reward terms, requester records, eligibility hints and deadlines are persisted in D1.
- Repeated polls update the same task row and preserve the owner-approval state.
- Poll failures are recorded in `swarmmemo_poll_state`; the product-copy worker continues independently.
- Authenticated operators can inspect the queue at `GET /v1/swarmmemo/work`.
- An authenticated operator can mark an open, eligible task as approved at `POST /v1/swarmmemo/work/{task_id}/approve`.

## Safety and current boundary

This is deliberately **not yet an autonomous claimant or submitter**. It does not create a SwarmMemo identity, sign messages, post replies, claim work, submit deliverables, or move funds. Approval changes the row to `approved_awaiting_executor`; it does not trigger an external action.

Task descriptions and feed fields are untrusted input. The lane stores them as data only and never interprets them as instructions. Eligibility is a board-provided hint, not proof that a task is safe or profitable. Simulated tasks are excluded from approval. Before execution, the agent must independently fetch the full task, validate requester history, reward mechanics, deadline, workload and source requirements.

## Deploy

The migration `0004_swarmmemo_work.sql` is applied through the existing Cloudflare Worker deployment workflow after the PR is reviewed and merged. The worker must not be deployed before the migration exists in the remote D1 database.

No new secrets are required for read-only discovery. A future signed executor must use a separate SwarmMemo signing identity held as a Cloudflare Worker secret; never put a private key in the repository, GitHub Actions logs, or chat. Signing, public posting, claiming and submission remain disabled until that secure identity and an explicit execution-authorization policy are implemented and tested.

## API

All queue routes use the existing private Worker authorization guard.

- `GET /v1/swarmmemo/work?limit=50`
- `POST /v1/swarmmemo/work/{task_id}/approve`

The response explicitly reports that discovery is not a claim, submission or payment.


## Hosted identity bootstrap (no local private key)

The Worker includes a one-time hosted-identity bootstrap through SwarmMemo's full MCP endpoint. It does not store the returned bearer URL or recovery code in D1, GitHub, or logs.

After this branch is reviewed, merged, the D1 migrations are applied, and the Worker is deployed:

1. Call authenticated `POST /v1/swarmmemo/identity/bootstrap` once. It calls SwarmMemo `create_identity` and returns the identity MCP URL and recovery code exactly once.
2. Save the recovery code privately and separately; it is needed to recover or later claim the hosted identity.
3. Add the exact returned MCP URL as a Cloudflare Worker secret named `SWARMMEMO_MCP_URL`.
4. Call authenticated `GET /v1/swarmmemo/identity/test`. It performs a read-only `find_work` call and confirms the hosted identity connection.
5. Check `GET /v1/swarmmemo/identity/status` for the identity fingerprint and secret-presence status.

The bootstrap reserves a single identity attempt before making the external call. If the outcome is uncertain, it refuses automatic retries to avoid creating duplicate identities. The bootstrap response contains bearer credentials and must be handled as a password. Do not paste them into chat or commit them.

This adds identity connectivity only. It does not automatically claim, post, submit, accept work, or transfer funds. The paid-task executor remains gated pending separate implementation, tests, and explicit authorization.
