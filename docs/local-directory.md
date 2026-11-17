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

Open `http://127.0.0.1:8765/` on the same device for the mobile-friendly read-only page, or `http://127.0.0.1:8765/v1/directory/services` for JSON.

Supported routes:
- `GET /` — mobile-friendly read-only service directory with escaped listing content.
- `GET /health` — minimal health response.
- `GET /v1/directory/services` — active listings only.
- Optional query parameters: `q`, `category`, `limit` (1-100).

All fields are explicitly allowlisted. Private participant identity claims, internal notes, signing material and database rows are not serialized. Unsupported query parameters, duplicate parameters, invalid limits and write methods are rejected. Unexpected catalog errors return a generic response without exception details.

## Deliberate limitations

- The CLI binds only to `127.0.0.1`; it does not accept a public host bind option.
- This is not a public marketplace deployment or participant dashboard.
- There are no write endpoints, registration, login, request authentication, user-specific views, moderation tools or payment flows.
- Do not change the bind address or put this service behind a public reverse proxy until production authentication, authorization, rate limits, privacy controls, abuse handling, monitoring and security review are complete.
- The local service catalog and SQLite database are prototype storage, not production infrastructure.
