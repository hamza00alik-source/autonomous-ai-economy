# Signed Request Authentication

Status: local authentication component; no HTTP server or public API is deployed.

## Protocol

Authenticated participant requests are signed with the participant's currently bound Ed25519 key. The canonical UTF-8 message is newline-delimited:

1. Protocol label: `AAE-HTTP-SIGNATURE-V1`
2. Uppercase HTTP method
3. Exact absolute request path (including query string, if any)
4. Lowercase SHA-256 digest of the exact request body bytes
5. Unix timestamp in seconds
6. One-time URL-safe nonce (16-128 characters)

The signature is Ed25519 over those exact bytes. The request must arrive within the configured clock-skew window (default 300 seconds). The nonce is consumed atomically in SQLite for the participant and cannot be reused until its expiry has passed.

## Local use

Install the optional crypto dependency:

```bash
pip install -e ".[identity]"
```

Example integration pseudocode:

```python
from economy.identity import ParticipantRegistry
from economy.request_auth import RequestAuthenticator

registry = ParticipantRegistry("./data/participants.sqlite3")
auth = RequestAuthenticator(registry, "./data/request-replay.sqlite3")

principal = auth.authenticate(
    participant_id=SIGNED_PARTICIPANT_ID,
    method="POST",
    path="/v1/tasks/offers",
    body=exact_raw_body_bytes,
    timestamp=UNIX_TIMESTAMP,
    nonce=ONE_TIME_NONCE,
    signature=BASE64URL_ED25519_SIGNATURE,
)
```

A web framework adapter must pass the exact raw request body and exact canonical path, enforce TLS, impose request-size limits, and call the policy engine for route/action authorization after authentication. Authentication alone does not authorize a task, listing, owner operation or financial action.

## Security properties and limitations

- Rejects unknown, suspended and revoked participants.
- Rejects participants without a currently bound public key.
- Binds signatures to method, path, body digest, timestamp and nonce.
- Rejects stale requests and invalid signatures.
- Atomically consumes each nonce to prevent replay, including concurrent duplicate requests.
- A rotated key takes effect because each request resolves the participant's current public key from the registry.
- The replay database must be durable and shared consistently by every API replica. A local SQLite file is not a distributed replay store.
- No TLS server, rate limiter, API gateway, WebAuthn, account recovery, session management, key revocation API, production database or public endpoint is included.
- Do not expose this local component or SQLite files directly to the internet.
- Production requires independent security review, operational monitoring, database backup/restore tests, rate limiting, privacy controls and an authenticated owner administration path.
