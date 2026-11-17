# Implementation Status

Last reviewed: 2026-11-17

## Shipped local prototype foundations

- Deterministic specialist agents, task controller, simulated append-only ledger and persistent SQLite task queue/one-shot worker. Worker claims are restricted to exact registered agent IDs; each claim receives a rotating secret lease token, completion/failure checks token ownership and lease expiry, and terminal transitions revoke the token.
- Default built-in handlers require Bubblewrap (`bwrap`) and fail closed if it is unavailable. The child runs with unshared namespaces (including network), all Linux capabilities dropped, UID/GID 65534 inside the namespace, a minimal environment, read-only runtime mounts, hidden home directories, temporary `/tmp` and `/work`, a fixed handler allowlist, a wall-clock timeout, and inherited POSIX CPU-time, address-space, file-size and file-descriptor limits. A reviewed architecture-specific seccomp-BPF denylist blocks socket creation and selected high-risk kernel interfaces (including ptrace, mount operations, BPF, perf events, userfaultfd and io_uring). The child reports its kernel-observed UID/GID, rlimits, seccomp mode and a blocked-socket probe; the parent rejects results unless every value matches the configured policy. The worker checks for Bubblewrap before claiming a task, so missing isolation leaves queued work untouched.
- This is a meaningful Linux namespace boundary for the trusted built-in deterministic handlers, not a complete hostile-code sandbox. There are no cgroup-level memory/CPU quotas or comprehensive syscall allowlist, and kernel/container escape risk remains. The seccomp policy is a targeted denylist, not a complete syscall confinement policy. The unprivileged namespace identity and inherited rlimits are defense-in-depth, not certification for hostile code. Injected custom registries still run in-process and must not contain untrusted code.
- Evidence-first opportunity validation, public research discovery leads, source retrieval/review, opportunity prioritization and unit-economics scenarios.
- Shared Brain and evidence-linked collective-learning proposals with owner review.
- Human, agent and organization participant records; Ed25519 agent enrollment, human/organization signing-key proof of possession, dual-proof key rotation and retired-key history.
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
- No production authentication/session system, WebAuthn/passkeys, lost-key recovery, remote credential/DID verification, KYC provider or abuse/Sybil controls.
- No always-on hosted scheduler/worker, distributed queue, cgroup-enforced resource quotas, comprehensive seccomp syscall allowlist, hostile-code sandbox, autonomous model routing or continuous offline agent team. The default worker requires Bubblewrap and may remain unavailable on hosts where user namespaces are disabled.
- No production owner console, remote issuer authentication, unified external-action gateway, hardened key management or tamper-proof audit store.
- No independent evidence verification, appeal workflow, formal dispute policy, legal contract workflow, refunds or settlement.
- No live customer acquisition or confirmed paying customer. Simulated demo revenue is not actual income.
- No payment provider, bank, wallet, escrow, custody, treasury transfer or blockchain transaction integration.

## Safety gates

- Keep the project separate from OpenCompany.
- Keep all external publishing and customer commitments disabled until the relevant exact-scope owner approval is integrated and reviewed.
- Never expose local SQLite/CLI prototypes to the public internet.
- Keep secrets outside source control; use distinct secrets for opportunity, catalog and generic action approvals.
- No paid infrastructure, metered model/API use, spending or financial actions without explicit owner approval.
- Live commerce requires security, privacy, local legal/tax and payment-provider eligibility review.
- A policy decision of `allow` is not an execution command; no external action is performed by the current policy engine.

## Next engineering sequence

1. Complete regression/security review of the local marketplace lifecycle and authorization boundaries, including explicit participant-to-task assignment.
2. Define and test lost-key recovery policy; strengthen audit integrity.
3. Add cgroup-enforced resource ceilings and evolve the targeted seccomp denylist into a reviewed, tested syscall allowlist before considering hostile-code execution.
4. Design production authentication, public API, rate limits, abuse handling and privacy boundaries before exposing registration or discovery.
5. Build a browser/mobile-friendly owner and participant console for the sandbox marketplace.
6. Add independent work verification, dispute responses, appeals and task amendment workflows.
7. Add durable scheduled workers only after sandbox and cost controls are independently reviewed.
8. Validate one real, legally permitted paying-customer workflow before considering live payment integrations or scaling.

This status distinguishes local prototype code from the future open economy. A committed module is not the same as a deployed, secure or revenue-producing service.
