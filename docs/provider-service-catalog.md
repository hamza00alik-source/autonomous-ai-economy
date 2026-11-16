# Provider Service Catalog

## Implemented local prototype

- Registered human, agent and organization participants with a bound signing key can create provider-signed service listing drafts.
- Drafts include a unique slug, title, description, category, delivery format, terms and optional fixed price/currency.
- Drafts are never discoverable through the public-catalog query.
- Publication requires an explicitly supplied owner approval verifier to validate the approval reference against the exact listing fingerprint.
- Published listings can be discovered by text/category; providers can withdraw their own listing with a signed request.
- Catalog events record draft creation, publication and withdrawal.

## Approval integration boundary

`ServiceCatalog.publish` deliberately has no default approval verifier. The preferred local path is `CatalogApprovalStore` plus `ServiceCatalog.publish_with_token`: the HMAC token is bound to the exact listing fingerprint, has a short expiry, and is consumed once. Use the separate `ECONOMY_CATALOG_APPROVAL_SECRET` (at least 32 bytes); never reuse the opportunity approval token format or secret. Token creation must happen only after the owner has reviewed and explicitly approved that exact listing. Protect the secret as a local owner credential. The lower-level callback API remains available for a future hardened approval service, but must never receive an arbitrary or user-controlled callback.


## Single-use local owner approval example

```python
from economy.service_catalog import CatalogApprovalStore, ServiceCatalog

catalog = ServiceCatalog("./data/participants.sqlite3")
listing = catalog.get(LISTING_ID)
approval_payload = catalog.publication_payload(listing["listing_id"], listing["payload"])

# Run this only after the owner has reviewed and explicitly approved the exact listing.
token = CatalogApprovalStore.create_token(
    listing["listing_id"], approval_payload, CATALOG_APPROVAL_SECRET
)
published = catalog.publish_with_token(
    listing["listing_id"], approval_token=token,
    approval_secret=CATALOG_APPROVAL_SECRET,
)
```

## Signing

- Build provider draft bytes using `ServiceCatalog.listing_signing_bytes(...)`.
- Sign with the provider agent's Ed25519 private key.
- Encode the signature as URL-safe base64 without padding.
- Withdrawal bytes are available from `ServiceCatalog.withdrawal_signing_bytes(listing_id, provider_id)`.

## Limits

- Local SQLite catalog only; no public HTTP API, marketplace website, search engine indexing, order processing, messaging, customer commitments or payments.
- Human and organization participants can bind an Ed25519 key by proof of possession; this is not legal identity verification or passkey/WebAuthn authentication.
- Listing content and provider signatures do not prove quality, legal compliance, customer demand or the provider's ability to fulfil the offer.
- A published listing is only a discoverable offer. It does not create a contract or authorize spending, payment, custody or transfer.
- Owner approval integration remains a hard gate before any production publication.
