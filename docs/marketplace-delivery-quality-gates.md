# Marketplace delivery quality gates

## Purpose

Opportunity discovery is not revenue. AAE must produce a usable deliverable that matches the buyer's actual requirements, inspect the exact draft, and obtain a separate-provider review before a task can become a submission candidate.

This remains a private draft pipeline. It does not claim, pitch, submit, publish, message buyers, sign transactions, or transfer funds.

## Execution flow

1. Preserve the buyer brief, acceptance criteria, deliverables, constraints and output format.
2. Preflight the configured independent reviewer service. Research/comparison tasks also preflight the source-verifier service. A missing binding, token, explicit enable flag, Gateway attestation or healthy service blocks before specialist inference.
3. Produce a private draft using the specialist model (Cloudflare Workers AI).
4. Run the existing same-model second-pass review. This is labelled as same-model review, not independent verification. One bounded revision is allowed.
5. Retrieve source pages through the separate Source Verifier for research/comparison tasks.
6. Send the exact draft and bounded source excerpts to the separate Google Gemini reviewer. The adapter accepts independent status only when the service reports provider=google, independent=true and sameProvider=false.
7. Run deterministic QA for content, exact evidence excerpts, source retrieval, acceptance criteria, same-model review and independent-provider review.
8. Mark a draft as a submission candidate only when both reviews and every deterministic gate pass. Otherwise retain it as blocked with the QA record.
9. Release reserved Workers AI budget when preflight blocks before inference.

## Separate Cloudflare services

### Source Verifier

The parent Worker calls only the authenticated SOURCE_VERIFIER service binding. The separate Worker uses a Workers VPC Network binding named EGRESS and never falls back to global fetch for user-provided URLs.

Application controls:
- Exact hostname allowlist (no wildcard/subdomain expansion)
- HTTPS only, default port 443, no credentials or IP-literal URLs
- Redirects disabled; caller must submit canonical URL
- Maximum eight URLs, 8-second per-request timeout and 1 MB response cap
- HTML/XHTML/plain-text content types only; scripts/styles are excluded from extracted text
- Internal service token required

The VPC Network public-egress path is routed through Cloudflare Gateway. Configure Gateway DNS/HTTP policies to allow only the exact source hosts, and Network policies to deny all private, loopback, link-local, reserved and other non-global IPv4/IPv6 destinations. Enable the Gateway proxy for Network and HTTP policies. The VPC configuration uses cf1:network. Cloudflare documents that Workers VPC public Internet traffic is subject to Gateway policies and logs.

The code requires the EGRESS binding, exact ALLOWED_SOURCE_HOSTS, an INTERNAL_SERVICE_TOKEN and EGRESS_POLICY_ATTESTATION=aae-source-egress-v1 before outbound requests. The parent also requires SOURCE_VERIFIER_TOKEN. An authenticated /healthz endpoint confirms configuration markers without making an outbound request.

**Evidence semantics:** the service returns status=retrieved_unverified, retrievalVerified=true, supportsClaims=false, a SHA-256 digest and (when found) an exact source excerpt also present in the draft. It proves retrieval and excerpt matching only; it does not certify source trust or semantic claim support. The independent reviewer receives the excerpt and separately evaluates whether it supports the draft's claims.

The attestation secret is an operator acknowledgement, not cryptographic proof that Gateway rules are correct. Do not set it until Gateway policies are configured, Gateway logs are reviewed, and a controlled DNS-rebinding test confirms that a private/reserved answer is blocked on the actual connection path. Until then the service returns unavailable and research tasks remain blocked.

See [Source Verifier README](../cloudflare/source-verifier/README.md).

### Independent Google reviewer

The separate AAE Independent Reviewer Worker calls Google's Gemini API at a fixed host through its own VPC/Gateway EGRESS binding. It does not use the specialist's Cloudflare model for the independent pass.

The service requires:
- VPC EGRESS binding and Gateway policy restricted to generativelanguage.googleapis.com over HTTPS
- INTERNAL_REVIEW_TOKEN
- GEMINI_API_KEY stored only in the reviewer Worker
- EGRESS_POLICY_ATTESTATION=aae-review-egress-v1
- INDEPENDENT_REVIEW_ENABLED=true

The parent Worker also requires the matching INDEPENDENT_REVIEW_TOKEN and INDEPENDENT_REVIEW_ENABLED=true. Both Wrangler configs default the enable flag to false. The health check validates configuration markers without calling Google. Google API calls may incur charges depending on the account's free-tier eligibility, quota and billing setup; check those and the provider's data-use terms before enabling.

See [Independent Reviewer README](../cloudflare/independent-reviewer/README.md).

## Required secrets and activation

No credentials or Gateway policies are committed to source control.

- Parent Worker: SOURCE_VERIFIER_TOKEN and INDEPENDENT_REVIEW_TOKEN.
- Source Verifier Worker: INTERNAL_SERVICE_TOKEN and EGRESS_POLICY_ATTESTATION; ALLOWED_SOURCE_HOSTS is an exact comma-separated host list.
- Independent Reviewer Worker: INTERNAL_REVIEW_TOKEN, GEMINI_API_KEY and EGRESS_POLICY_ATTESTATION; INDEPENDENT_REVIEW_ENABLED remains false until provider cost/privacy review.
- The corresponding parent and child service tokens must match.

Both service bindings are present in the proposed parent Wrangler config, but the service workers are not deployed and no secrets, allowlists or Gateway policies have been configured. The health endpoints and attestation checks do not prove the live network policy; actual adversarial egress testing remains a deployment gate.

## Marketplace screening and execution boundary

The task assessor blocks unsuitable deliverables including long-form video production, non-USDC token rewards such as FLAPJAX, and tasks requiring external financial settlement/account access. The task queue only marks an item draft-ready when the executor returns submission_candidate and submissionReady=true.

### Automatic Taskmarket submission

QA-passed Taskmarket Base bounty drafts can be submitted automatically without a per-task owner approval step, but only after the dedicated signer service is configured and the explicit `TASKMARKET_SUBMISSION_ENABLED=true` flag is set. The adapter:

- Supports Base mainnet bounty mode only; it does not claim, pitch, bid, post, publish, or contact buyers.
- Re-fetches the task and checks that it remains open, unexpired, unchanged, escrow-backed, unstaked, and on chain 8453.
- Requires a separately configured `WALLET_SIGNER` service binding. The signer must expose authenticated `GET /healthz` returning `{ok:true,address,chainId:8453,signing:"eip191"}`, and authenticated `POST /v1/sign` accepting only the exact `taskmarket:submit:<taskId>` message. The Worker pins the expected wallet address and never stores a private key.
- Checks for an existing submission from the worker before writing.
- Submits only while the task's total submission count is below 50. Taskmarket makes each worker's first five bounty submissions free until the task reaches 50 total submissions; the adapter submits at most once per worker/task and makes no x402-paid call.
- Sends the QA-passed Markdown deliverable with the required EIP-191 signature. An ambiguous network result is marked for reconciliation and is never automatically retried.
- Retries stored QA-passed drafts on the five-minute schedule once the signer is available. There is no per-task approval gate after QA; the global feature flag and signer provisioning are one-time operator setup.

The feature flag defaults to false. No signer binding, signer token, worker address or wallet key is committed. Until an isolated signer is deployed and its address is pinned, candidates remain private drafts. The Taskmarket API documents the EIP-191 submission message and first-five-free allowance; see [Taskmarket API](https://docs.taskmarket.dev/api/reference) and [submission rules](https://docs.taskmarket.dev/tasks/earning/submitting).

No live task has been claimed or submitted by this code change. A successful API response must still be checked against the worker's submission list and on-chain payout records. Internal QA is not buyer acceptance or payment.

## Validation

CI runs:
- Python source-fetcher unit and live local TLS/socket integration tests, including simulated DNS rebinding and certificate hostname mismatch
- Private Worker logic tests
- Source Verifier and Independent Reviewer service tests, including fail-closed health and egress behavior
- Wrangler dry-run builds for the parent Worker and both isolated services

A passing CI run validates code and configuration syntax only. It does not validate Cloudflare Gateway account policies, Google API credentials, live external egress, buyer acceptance or revenue.
