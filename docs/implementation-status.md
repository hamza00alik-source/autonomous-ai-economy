# Implementation Status

Last reviewed: 2026-11-17

## Shipped local prototype foundations

- Deterministic specialist agents, task controller, simulated append-only ledger, persistent SQLite task queue/one-shot worker, and long-running single-host supervisor (`economy-supervisor`) with bounded polling, graceful SIGTERM/SIGINT shutdown and basic cycle counters. A hardened systemd unit template is provided. This is not hosted uptime, HA, distributed scheduling or a production deployment. Worker claims are restricted to exact registered agent IDs; each claim receives a rotating secret lease token, completion/failure checks token ownership and lease expiry, and terminal transitions revoke the token.
- Default built-in handlers require Bubblewrap (`bwrap`) and fail closed if it is unavailable. The child runs with unshared namespaces (including network), all Linux capabilities dropped, UID/GID 65534 inside the namespace, a minimal environment, read-only runtime mounts, hidden home directories, temporary `/tmp` and `/work`, a fixed handler allowlist, a wall-clock timeout, and inherited POSIX CPU-time, address-space, file-size and file-descriptor limits. A reviewed architecture-specific seccomp-BPF denylist blocks alternate x32 ABI execution on x86_64 and blocks socket creation and selected high-risk kernel interfaces (including ptrace, mount operations, BPF, perf events, userfaultfd and io_uring). The child reports its kernel-observed UID/GID, rlimits, seccomp mode and a blocked-socket probe; the parent rejects results unless every value matches the configured policy. When `AAE_CGROUP_ROOT` is explicitly configured to a delegated cgroup v2 subtree with cpu, memory and pids controllers already enabled, the runner also creates a per-task cgroup with `memory.max=536870912`, `cpu.max=100000 100000` (one CPU of quota) and `pids.max=16`, attaches the Bubblewrap process before exec, and verifies the kernel retained the configured limits. Invalid delegation fails during worker preflight before a task is claimed. The worker checks for Bubblewrap before claiming a task, so missing isolation leaves queued work untouched.
- This is a meaningful Linux namespace boundary for the trusted built-in deterministic handlers, not a complete hostile-code sandbox. Cgroup ceilings are optional and are not active unless `AAE_CGROUP_ROOT` points to a correctly delegated subtree; CI currently exercises cgroup configuration with filesystem fixtures, not a privileged live cgroup integration test. There is no comprehensive syscall allowlist, and kernel/container escape risk remains. The seccomp policy is a targeted denylist, not a complete syscall confinement policy. The unprivileged namespace identity and inherited rlimits are defense-in-depth, not certification for hostile code. Injected custom registries still run in-process and must not contain untrusted code.
- Evidence-first opportunity validation, public research discovery leads, source retrieval/review, opportunity prioritization and unit-economics scenarios.
- Shared Brain and evidence-linked collective-learning proposals with owner review.
- Human, agent and organization participant records; Ed25519 agent enrollment, human/organization signing-key proof of possession, dual-proof key rotation and retired-key history. Participant emergency lock atomically suspends an account and invalidates pending key challenges; a participant-scoped SQLite limiter enforces quotas for key challenges and task-offer operations, and records rejected quota attempts in an owner-reviewed abuse queue. Startup migrates an intermediate development schema that incorrectly limited reviewed cases, preserving history and restoring the one-open-case partial index. Local review outcomes are dismiss/monitor/escalate only and never automatically penalize accounts. See [participant abuse and account recovery runbook](participant-abuse-and-account-recovery-runbook.md).
- Signed bounded agent delegation with trusted-root pinning, signer-key binding, narrowing, expiry, amount/currency limits, depth limits, ancestor revocation and invalidation after key rotation.
- Scoped capability grants, deny-by-default authorization, participant suspension checks and audit records.
- Framework-independent Ed25519 signed-request authentication with method/path/body binding, timestamp window and atomic nonce replay protection (local component only).
- Read-only WSGI service directory with a mobile-friendly HTML page, allowlisted active listings and a signed-request authenticated self-profile endpoint; HTML escaping and loopback-only CLI server.
- Explicit task assignment to an existing active, cryptographically key-bound agent participant; assignment never guesses from handles or role names, and authenticated task listing uses the participant ID.
- Local PolicyEngine combining capabilities or delegation with short-lived, exact-request, single-use HMAC owner approvals. It returns decisions only and executes no external action.
- Provider-signed service listing drafts, exact-listing single-use owner approval, local discovery and provider withdrawal.
- Buyer-signed task offers, provider acceptance/decline, buyer withdrawal, and work receipts linked to accepted task agreements.
- Buyer acceptance, signed disputes, trusted adjudicator resolutions and conservative outcome-derived reputation counts.
- CI test workflow on Python 3.11.

## Not shipped / not yet production-ready

- No public participant registration, public marketplace deployment, authenticated participant API, marketplace website, or external search indexing. The local read-only directory is not a public service.
- No production authentication/session system, WebAuthn/passkeys, lost-key recovery, remote credential/DID verification, KYC provider, distributed/IP-level rate limiting, registration/Sybil defenses, or production abuse monitoring. The local participant quotas and owner-review queue are prototype controls only.
- No hosted always-on scheduler/worker, distributed queue, high availability, default-enabled cgroup quotas, comprehensive seccomp syscall allowlist, hostile-code sandbox, autonomous model routing or continuous offline agent team. The default worker requires Bubblewrap and may remain unavailable on hosts where user namespaces are disabled.
- No production owner console, remote issuer authentication, unified external-action gateway, hardened key management or tamper-proof audit store.
- No independent evidence verification, appeal workflow, formal dispute policy, legal contract workflow, refunds or settlement.
- No live customer acquisition or confirmed paying customer. Simulated demo revenue is not actual income.
- No payment provider, bank, wallet, escrow, custody, treasury transfer or blockchain transaction integration.

## Signed task-offer API

The local WSGI application supports `POST /v1/tasks/offers`, `POST /v1/tasks/{id}/responses`, `GET /v1/tasks/offers/inbox`, and participant-only `GET /v1/tasks/{id}`. The HTTP request must be signed by the participant's bound Ed25519 key; the offer or provider decision also carries the existing independent agreement signature. Buyer/provider identity is derived from the authenticated participant, not caller-supplied identity fields. Request bodies are capped at 16 KiB, query parameters and duplicate JSON keys are rejected, and responses are allowlisted. No payment intent, escrow, funds reservation, external publication or execution side effect occurs. Tests use authenticator/agreement test doubles for the HTTP boundary; existing domain-store tests cover agreement signature validation. This does not constitute production authentication, rate limiting, TLS, account recovery or deployment.

## Always-on supervisor

Install the package and run `economy-supervisor --data-dir /var/lib/autonomous-ai-economy --poll-seconds 2`. The process uses the existing local durable queue and fixed built-in worker, and should be managed by a process supervisor such as the supplied systemd unit. It requires the same Linux Bubblewrap availability as the default worker. The systemd template is a starting point and must be reviewed against the target host's namespace, cgroup and filesystem policies. It does not provide distributed locking, multi-host coordination, remote monitoring, backup or service-level guarantees. See [always-on runtime and production launch gates](always-on-production-launch-gates.md).

## Optional delegated cgroup configuration

Set `AAE_CGROUP_ROOT` in the worker process environment to an administrator-delegated cgroup v2 directory. The directory must be on a cgroup2 mount and have `cpu`, `memory` and `pids` enabled in both `cgroup.controllers` and `cgroup.subtree_control`. The application does not enable controllers or modify system-wide cgroup configuration. If configured incorrectly, worker preflight fails closed before claiming tasks. If unset, POSIX rlimits still apply but cgroup ceilings are not active.

## Safety gates

- Keep the project separate from OpenCompany.
- Keep all external publishing and customer commitments disabled until the relevant exact-scope owner approval is integrated and reviewed.
- Never expose local SQLite/CLI prototypes to the public internet.
- Keep secrets outside source control; use distinct secrets for opportunity, catalog and generic action approvals.
- No paid infrastructure, metered model/API use, spending or financial actions without explicit owner approval.
- Live commerce requires security, privacy, local legal/tax and payment-provider eligibility review.
- A policy decision of `allow` is not an execution command; no external action is performed by the current policy engine.

## Next commercial sequence

1. Validate the first-revenue pilot offer and sample delivery against current public marketplace policy and customer expectations.
2. Owner verifies Upwork account eligibility, identity/tax requirements, exact Project Catalog creation workflow on Android, and the actual withdrawal methods/fees shown in the account.
3. Owner reviews and explicitly approves the final project listing, price, delivery window and sample before any publication.
4. Publish only after that approval; measure impressions, clicks, enquiries, orders, cancellations and cleared net receipts.
5. Fulfil any first order under owner supervision, using only public sources and free tools unless separate spending approval is granted.
6. Record first revenue only after cleared funds are received and reconciled after fees.

The fixed-scope Etsy listing audit is a commercial hypothesis, not a validated source of guaranteed sales. Its research basis, exact deliverables, limitations, owner approval gates and success definition are in [first-revenue pilot](first-revenue-pilot.md). No external listing has been created or published, and no customer or revenue exists yet.

## Next engineering sequence

1. Complete the minimum local marketplace and authorization work needed to record an owner-supervised pilot transaction without pretending a local ledger is payment processing.
2. Continue security and recovery work only where it directly blocks safe customer delivery or participant protection.
3. Keep public deployment, payments, custody, autonomous transfers and always-on hosted infrastructure gated until separate security, legal, provider and owner approvals.

This status distinguishes local prototype code from the future open economy. A committed module is not the same as a deployed, secure or revenue-producing service.
