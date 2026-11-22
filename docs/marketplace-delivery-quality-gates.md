# Marketplace delivery quality gates

## Purpose

Opportunity discovery is not revenue. AAE must produce a usable deliverable that matches the buyer's actual requirements, then inspect that exact deliverable before it can be marked as a submission candidate.

This workflow is a private draft pipeline. It does not claim work, pay fees, sign transactions, submit deliverables, or contact buyers.

## Execution flow

1. Preserve the buyer brief, explicit acceptance criteria, deliverables, constraints, and output format.
2. Produce a private draft using the specialist agent.
3. Have a separate reviewer assess the exact draft and each criterion. Evidence excerpts must be verbatim substrings of the draft.
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

- The current LLM reviewer is a separate model call but not a different provider or independent source of truth.
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
