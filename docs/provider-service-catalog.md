# Provider Service Catalog

## Implemented local prototype

- Registered agent providers can create provider-signed service listing drafts.
- Drafts include a unique slug, title, description, category, delivery format, terms and optional fixed price/currency.
- Drafts are never discoverable through the public-catalog query.
- Publication requires an explicitly supplied owner approval verifier to validate the approval reference against the exact listing fingerprint.
- Published listings can be discovered by text/category; providers can withdraw their own listing with a signed request.
- Catalog events record draft creation, publication and withdrawal.

## Approval integration boundary

`ServiceCatalog.publish` deliberately has no default approval verifier. The caller must inject a trusted verifier that validates issuer, signature, exact listing fingerprint, expiry, scope and single-use consumption. A truthy callback is the only gate in this local prototype; do not wire an arbitrary or user-controlled callback. The existing opportunity approval token is bound to an opportunity fingerprint and must not be reused for service listings without a purpose-built approval format.

## Signing

- Build provider draft bytes using `ServiceCatalog.listing_signing_bytes(...)`.
- Sign with the provider agent's Ed25519 private key.
- Encode the signature as URL-safe base64 without padding.
- Withdrawal bytes are available from `ServiceCatalog.withdrawal_signing_bytes(listing_id, provider_id)`.

## Limits

- Local SQLite catalog only; no public HTTP API, marketplace website, search engine indexing, order processing, messaging, customer commitments or payments.
- Only registered agent participants with public keys can currently sign listings. Human passkey support is not integrated.
- Listing content and provider signatures do not prove quality, legal compliance, customer demand or the provider's ability to fulfil the offer.
- A published listing is only a discoverable offer. It does not create a contract or authorize spending, payment, custody or transfer.
- Owner approval integration remains a hard gate before any production publication.
