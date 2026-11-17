# Work Receipts, Disputes and Reputation

## Implemented local prototype

- Provider-signed work submission receipts bind a unique task ID, provider, buyer, summary and evidence references.
- Buyer-signed acceptance is required before a receipt counts as accepted. Acceptance signature version 2 binds the exact task/agreement ID, canonical accepted-offer digest, buyer/provider IDs, receipt ID, and sorted artifact SHA-256 digests claimed by the receipt.
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
- Human passkey signing and verified buyer identity are not integrated yet; the local receipt flow currently requires registered public keys. Buyer acceptance signs a version-2 payload bound to the accepted offer digest and artifact digest list; it remains a buyer assertion, not independent proof of quality or delivery.
- No payment, escrow, custody, automatic payout or financial settlement is connected.
- Test suites inject a verifier for deterministic tests; production uses Ed25519 verification.

## Local artifact-byte verification (new)

- `economy.artifact_evidence.verify_local_artifact(path, manifest)` validates a strict versioned manifest and independently hashes a file supplied by the operator.
- Manifest fields are exactly `schema`, `sha256`, `size_bytes` and `media_type`. SHA-256 must be 64 lowercase hex characters; size is bounded to 100 MiB; symlinks and non-regular files are rejected.
- Verification is local-only: no URL fetching, remote host access, or SSRF-capable behavior is introduced. A matching digest confirms that the bytes read by the verifier match the manifest's claimed digest and size.
- This does not prove who created or uploaded the file, when it existed, whether the manifest was truthful, or whether the work meets the buyer's criteria. A local file can also be changed after verification; production use needs immutable/content-addressed storage and a separately trusted timestamp/receipt.
- This helper is not wired into acceptance, reputation, payouts, or payment. Buyer acceptance remains a separate signed assertion, and no money movement is enabled.


## Local command-line artifact workflow

The local CLI can create and check a manifest without network access:

```bash
economy artifact-manifest ./deliverable.zip --media-type application/zip > manifest.json
economy artifact-verify ./deliverable.zip ./manifest.json
```

The first command hashes the bytes currently present and prints a manifest. The second independently hashes the supplied local file and exits non-zero on mismatch. Share the artifact and manifest through a separately chosen delivery channel; the commands do not upload, publish, or deliver either file.

For buyer acceptance, the buyer must obtain the artifact independently, run `artifact-verify`, then request the exact payload with `WorkRecordStore.acceptance_signing_bytes(receipt_id, buyer_id=...)` and sign those bytes using the buyer's registered Ed25519 key before calling `accept(...)`. This remains an operator-driven local workflow, not a turnkey delivery integration. Avoid treating a successful earlier verification as durable if the file can change before acceptance; re-verify immediately before signing. No payout or settlement follows acceptance.
