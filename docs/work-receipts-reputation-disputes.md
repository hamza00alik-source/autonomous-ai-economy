# Work Receipts, Disputes and Reputation

## Implemented local prototype

- Provider-signed work submission receipts bind a unique task ID, provider, buyer, summary and evidence references.
- Buyer-signed acceptance is required before a receipt counts as accepted.
- Either party can open a signed dispute with a reason and evidence references.
- Only a locally configured trusted adjudicator key can sign a dispute resolution.
- Reputation is a conservative count summary derived from receipt states; it is not a star score, quality guarantee, identity verification or proof of commercial success.
- Evidence references are syntax-checked. `artifact:` references must be content-addressed as `artifact:sha256:<64 lowercase hex chars>`; HTTPS references must include a host and cannot embed credentials; task references must include a whitespace-free identifier.
- Pending and disputed receipts do not count as accepted. A resolved dispute is reported separately and is not silently converted into buyer acceptance.

## Signing payloads

Use the static payload helpers on `WorkRecordStore` to produce the exact bytes to sign:
- `submission_payload(...)` returns the provider submission object; sign its canonical JSON encoding (sorted keys, compact separators, UTF-8).
- `acceptance_payload(receipt_id, buyer_id, provider_id)` returns buyer acceptance bytes.
- `dispute_payload(...)` returns the participant dispute bytes.
- `resolution_payload(...)` returns adjudicator resolution bytes.

Sign with the participant's Ed25519 private key and encode the 64-byte signature as URL-safe base64 without padding. The local registry must contain the participant's active public key. The adjudicator ID-to-public-key map is injected by the trusted local application.

## Reputation semantics

The API reports counts for accepted, pending, disputed, and dispute outcomes. It intentionally does not calculate a weighted score or rank providers. Small samples, self-selection, collusion, evidence quality and adjudicator bias can all distort reputation. Production reputation requires anti-Sybil controls, buyer eligibility, independent verification, appeals, rate limits and transparent policy.

## Limitations

- SQLite local prototype; no public API, remote authentication, secure evidence hosting or immutable external timestamping.
- Evidence references are pointers, not independently verified facts. A signature proves control of a key, not that work was honestly or correctly performed.
- Content-addressed artifact references bind a receipt to a claimed SHA-256 digest, but the prototype does not download or retain the artifact, recompute its digest, establish who hosted it, or prove when it existed. A matching digest proves byte equality only when a verifier obtains the bytes and hashes them independently.
- The current prototype has no dispute response workflow, deadline policy, appeal process or independent adjudicator marketplace.
- Human passkey signing and verified buyer identity are not integrated yet; the local receipt flow currently requires registered public keys.
- No payment, escrow, custody, automatic payout or financial settlement is connected.
- Test suites inject a verifier for deterministic tests; production uses Ed25519 verification.
