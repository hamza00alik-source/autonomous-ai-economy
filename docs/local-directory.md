# Local Read-Only Service Directory

The prototype includes a minimal WSGI directory for viewing owner-approved active service listings. It is deliberately read-only and binds to loopback only.

## Run locally

Install the project:

```bash
pip install -e ".[identity]"
```

Start the directory:

```bash
economy serve-directory --data-dir ./data --port 8765
```

Open `http://127.0.0.1:8765/` for the mobile-friendly service directory, `http://127.0.0.1:8765/owner` for a loopback-only aggregate owner snapshot, or `http://127.0.0.1:8765/v1/directory/services` for JSON.

Supported routes:
- `GET /` — mobile-friendly read-only service directory with escaped listing content.
- `GET /owner` — loopback-only, aggregate-only HTML owner snapshot; no controls or write actions.
- `GET /health` — minimal health response.
- `GET /v1/directory/services` — active listings only.
- `GET /v1/participants/me` — requires a signed request using the participant's current Ed25519 key; returns only an allowlisted self-profile.
- `GET /v1/tasks/mine` — requires the same signed request authentication; returns only tasks assigned to the authenticated participant ID, with a minimal field allowlist.
- `GET /v1/local/owner/overview` — aggregate counts for participants, tasks and service listings; the handler rejects non-loopback client addresses and does not expose participant records or task contents.
- Optional query parameters: `q`, `category`, `limit` (1-100).

All fields are explicitly allowlisted. Private participant identity claims, internal notes, signing material and database rows are not serialized. Unsupported query parameters, duplicate parameters, invalid limits and write methods are rejected. Unexpected catalog errors return a generic response without exception details.

## Deliberate limitations

- The CLI binds only to `127.0.0.1`; it does not accept a public host bind option.
- This is not a public marketplace deployment or production owner dashboard. `/owner` is an aggregate-only local snapshot, not an authenticated administration console; loopback is a local-development boundary, not production authentication.
- There are no write endpoints, registration, account recovery, moderation tools or payment flows. The self-profile endpoint uses the local signed-request authenticator; this is not a production login/session system.
- Do not change the bind address or put this service behind a public reverse proxy until production authentication, authorization, rate limits, privacy controls, abuse handling, monitoring and security review are complete.
- The local service catalog and SQLite database are prototype storage, not production infrastructure.
