# Marketplace delivery quality gates

## Purpose

Opportunity discovery is not revenue. AAE must produce a usable deliverable that matches the buyer's actual requirements, then inspect that exact deliverable before it can be marked as a submission candidate.

This workflow is a private draft pipeline. It does not claim work, pay fees, sign transactions, submit deliverables, or contact buyers.

## Execution flow

1. Preserve the buyer brief, explicit acceptance criteria, deliverables, constraints, and output format.
2. Produce a private draft using the specialist agent.
3. Have a second review call assess the exact draft and each criterion. The current reviewer call uses the same Workers AI model as the specialist; it is a useful second pass, not an independent reviewer or source of truth. Evidence excerpts must be verbatim substrings of the draft.
4. Allow one bounded revision, then fail closed if defects remain.
5. Run deterministic checks for unfinished content, self-review, unsupported verification claims, acceptance criteria, and source evidence.
6. Store a SHA-256 integrity digest and the review/QA record.
7. Keep external claim, pitch, submission, publication, messaging, signature, and payment actions separately authorized.

## Trusted source-verifier adapter

Research/comparison tasks now call an optional Cloudflare Service Binding named `SOURCE_VERIFIER`. The core marketplace worker does not fetch user-controlled URLs itself. This avoids putting arbitrary outbound URL fetching in the privileged worker.

The service binding must implement `POST /v1/verify` and accept protocol version 1, a bounded list of up to eight URLs, the task brief, the draft, and explicit fetch limits. It must return protocol version 1 with status `verified` and exactly one result per requested URL. Each result must include:

- Exact `requestedUrl`, final HTTP 200 status, title, and final URL
- A valid SHA-256 digest of the fetched source content and an ISO timestamp
- A source excerpt from fetched content and a corresponding draft excerpt
- `supportsClaims: true`, meaning the verifier assessed the cited source as relevant support for the corresponding draft passage

The core worker validates the response shape, URL identity, digest format, timestamps, excerpt lengths, and that each draft excerpt is present in the actual draft. The binding itself is the trust boundary: its implementation MUST enforce HTTPS where possible, reject localhost/private/reserved IPs after DNS resolution, re-check every redirect target, prevent DNS rebinding, cap response bytes and total time, avoid forwarding credentials/cookies, avoid executing scripts, sanitize extracted text, and defend against prompt injection in page content. It must not return `verified` unless the fetched page and claim relevance were actually checked.

If the binding is absent, errors, times out, returns malformed evidence, or fails any check, research/comparison work remains blocked. No default public fetch fallback exists. Configure a separately reviewed and deployed verifier service before binding it to this worker. No service binding has been added to `wrangler.toml` yet, so this change alone does not activate remote verification.

## Remaining limitations

- The specialist and reviewer use the same Workers AI model (`@cf/zai-org/glm-4.7-flash`). The reviewer is a separate call, not a different model/provider or an independent source of truth. Runtime metadata reports `reviewMode: same_model_second_call` and `independentlyReviewed: false`.
- Exact quoted excerpts and a verifier attestation improve traceability; they do not mathematically prove that a source is true or that a buyer will accept the work.
- Code tasks requiring execution remain blocked until a secure sandbox is integrated.
- PDF, office documents, archives, images, 3D, audio, and video deliverables remain blocked until real generation and inspection pipelines exist.
- A passing internal review does not guarantee buyer acceptance, payment, or dispute-free completion.
- The pipeline prepares private drafts only. It does not claim, pitch, submit, publish, message, sign, spend, or transfer funds.

## Tests

From `cloudflare/worker`:

```bash
npm test
```

## Source-verifier security architecture decision (deployment gate)

A DNS preflight followed by ordinary `fetch()` is **not** sufficient to claim DNS-rebinding protection. Cloudflare Workers' global `fetch()` does not expose a supported arbitrary-destination IP-pinning control; `resolveOverride` is restricted to hostnames in the same Cloudflare zone. A separate DNS-over-HTTPS lookup followed by `fetch()` leaves a time-of-check/time-of-use gap because the connection can resolve the hostname again. Manual redirect handling is necessary but does not close that gap by itself.

Therefore, do not implement or deploy the verifier as a Worker that merely resolves A/AAAA records, rejects private results, then calls global `fetch()`. Do not label that design SSRF-safe.

### Required deployment topology

1. The AAE marketplace Worker calls only the authenticated `SOURCE_VERIFIER` service binding; no task-supplied URL is fetched by the marketplace Worker.
2. The verifier service validates the URL syntax and policy, then sends every outbound request through a dedicated egress fetcher/proxy with connection-time destination enforcement.
3. The egress component resolves both A and AAAA records, rejects every non-global/reserved address, and connects to a selected validated IP without a second uncontrolled DNS lookup. It preserves the original hostname for TLS SNI and certificate verification and the HTTP Host header.
4. Redirects are disabled at the HTTP client. The verifier parses each Location, re-applies the full URL and DNS/IP policy, and requests the next hop through the same pinned egress path. Limit redirect count.
5. Apply strict allow/deny policy, ports 80/443 only (prefer HTTPS), no userinfo, no cookies or ambient credentials, bounded connect/read/total time, bounded decompressed response bytes, content-type restrictions, and no script execution.
6. Record requested URL, each redirect hop, resolved addresses, selected peer IP, TLS hostname/certificate result, status, content digest, fetch timestamp, and bounded extracted evidence. Never expose internal IPs or sensitive transport details to marketplace users.
7. Add adversarial tests for IPv4 and IPv6 loopback/private/link-local/reserved ranges, IPv4-mapped IPv6, alternate numeric IP forms, mixed public/private DNS answers, rebinding between validation and connect, redirect-to-private, redirect loops, oversized compressed bodies, slow responses, and TLS hostname mismatch.

### Platform decision

Cloudflare Workers remains suitable as the authenticated control plane and service-binding client. It is not, by itself, the verified arbitrary-URL egress enforcement point for this threat model. The separate fetcher must demonstrate connection-time IP pinning and network egress restrictions in a reviewed implementation before the `SOURCE_VERIFIER` binding is configured. A DNS preflight plus Workers `fetch()`, or a hostname-only blocklist, does not meet this requirement.

Until that implementation and its adversarial tests are independently reviewed, `SOURCE_VERIFIER` must remain unbound and research tasks must remain blocked. This is an intentional security gate, not a completed feature.
