# Public API and Abuse-Control Design

Status: design specification only. No public API is deployed by this document.

## Security objective

Expose public discovery and low-risk participation without allowing anonymous callers to impersonate participants, enumerate private data, create unlimited work, spam providers, or reach owner/treasury controls. Public participation must be graduated and scoped.

## API boundaries

### Public read-only routes

- `GET /v1/directory/services` — only owner-approved active listings and explicitly public fields.
- `GET /v1/directory/participants/{public_id}` — only fields the participant opted to publish.
- `GET /v1/policy/participation-levels` — public policy explanation.
- `GET /health` — minimal health response; no environment, database, version-secret or infrastructure details.

### Registration and key control

- `POST /v1/participants` — create a low-trust participant record with a unique handle and minimal metadata.
- `POST /v1/participants/{id}/key-challenges` — issue a short-lived, one-time challenge.
- `POST /v1/participants/{id}/key-bindings` — verify proof of possession and bind the public key.
- `POST /v1/participants/{id}/key-rotations` — future two-key signed rotation with recovery and revocation rules; do not ship until designed and tested.
- Email, passkeys/WebAuthn and third-party credentials are separate future authentication methods. Key possession must never be represented as legal identity/KYC.

### Implemented local signed task-offer routes

The loopback WSGI prototype now accepts:

- `POST /v1/tasks/offers` — buyer-signed offer. The HTTP request itself must also be signed; the buyer identity is taken from the authenticated principal, never from a caller-supplied buyer ID. The referenced listing must be active and owned by the selected provider.
- `POST /v1/tasks/{id}/responses` — provider-signed accept/decline. The provider identity is taken from the authenticated principal.
- `GET /v1/tasks/offers/inbox` — authenticated provider inbox, with bounded status/limit filters signed as part of the exact request target.
- `GET /v1/tasks/{id}` — agreement status and terms visible only to the authenticated buyer or provider.

Both routes cap request bodies at 16 KiB, reject query parameters, duplicate JSON keys and unknown fields, authenticate the exact raw body and path, and return allowlisted response fields. Private agreement detail is hidden from all non-participants. These are local prototype endpoints, not public production endpoints. They do not create a payment intent, reserve funds, publish a listing or execute worker tasks. The offer payload signature is separate from the HTTP request signature because it binds the commercial agreement independently.

### Authenticated participant routes

- `POST /v1/services/drafts` — provider-signed draft only.
- `POST /v1/tasks/offers` — buyer-signed offer against an active listing.
- `POST /v1/tasks/{id}/responses` — provider-signed accept/decline.
- `POST /v1/work-receipts` — provider-signed evidence receipt for an accepted task.
- `POST /v1/work-receipts/{id}/acceptances` — buyer-signed acceptance.
- `POST /v1/work-receipts/{id}/disputes` — participant-signed dispute.
- `GET /v1/participants/me`, `GET /v1/tasks/me`, `GET /v1/audit/me` — only authenticated participant-owned records. The participant self-profile returns an allowlisted public profile plus `key_bound` and a truncated SHA-256 key fingerprint (`key_id`); it never returns the public-key material, private metadata or operator linkage.

### Owner-only routes (not to expose in first public release)

- Listing publication approval.
- Participant suspension, trust claims and moderator decisions.
- Adjudicator assignment and dispute resolution.
- Capability grants, delegation roots, policy configuration and secret rotation.
- Any financial/provider connection or transaction.

No owner-only route may be authorized by a participant-supplied role string or unverified `approval_ref`.

## Request authentication

For authenticated writes, use signed requests with:
- participant key ID and signature algorithm;
- HTTP method and canonical path;
- SHA-256 body digest;
- timestamp with a narrow acceptance window;
- unique nonce recorded server-side to prevent replay;
- request ID/idempotency key for retry-safe writes.

Reject stale timestamps, reused nonces, unknown/revoked keys, invalid signatures and mismatched body hashes. TLS is mandatory. Never place private keys in the API, logs or database.

## Rate limits and abuse controls

Apply limits at multiple dimensions:
- source IP/network and coarse device/session signals;
- participant ID and public-key fingerprint;
- route class, action and resource;
- new-account age and trust tier;
- listing creation, task offers, disputes and evidence uploads.

Use bounded payload sizes, pagination caps, idempotency, per-participant quotas, spam throttles, duplicate-content signals, report/appeal paths, and quarantine for suspicious behavior. Avoid relying on IP alone because of shared networks and VPNs. Avoid collecting invasive device fingerprints without a privacy/legal basis.

## Privacy and data minimization

- Separate public profile fields from private identity and operator claims.
- Keep evidence files private by default; expose only explicit public links or hashes.
- Never expose email, legal identity documents, private project data, internal notes, owner identifiers, secrets or other participants' audit logs through public endpoints.
- Record retention, deletion, legal hold and dispute evidence rules before live launch.
- Public discovery must use an allowlist serializer, not raw database rows.

## Operational architecture

Before production:
1. Put the API behind a maintained TLS reverse proxy/WAF and request-size limits.
2. Replace local SQLite with a managed, backed-up database when concurrent public use requires it.
3. Separate API, queue workers, object storage and secrets management.
4. Use transactional state changes, idempotency and an append-only audit export.
5. Add metrics, alerting, abuse monitoring, incident response, backups and tested restore.
6. Run dependency, static, secret, authorization and penetration testing.
7. Keep worker execution isolated with no default network or filesystem privileges.

## Release gates

Do not deploy public registration or the marketplace until request authentication, key revocation/rotation, owner authorization, rate limits, privacy policy, terms, moderation, appeals and incident response are implemented and tested. Do not connect payments or treasury in this phase. The current local SQLite prototypes are not safe to expose directly to the public internet. The signed offer routes are a narrow local protocol implementation, not a production launch authorization; abuse rate limits, public account onboarding, durable production storage, TLS edge, privacy and legal reviews remain mandatory.
