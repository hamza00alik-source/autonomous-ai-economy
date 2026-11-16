# Signed Delegation and Agent Authority

## Purpose

This module adds a bounded, cryptographically signed delegation chain from a trusted participant to an enrolled agent and, optionally, from that agent to another enrolled agent. It is separate from the prototype capability-grant CLI.

## Trust model

- A root delegation is accepted only when the delegator ID is explicitly pinned to an owner public key in the trusted-root configuration supplied to `DelegationStore`.
- A root signer must also be an active participant in the local registry.
- A child delegation must be signed by the parent delegation's current delegate.
- Delegates must be active registered agent participants with an enrolled Ed25519 public key.
- Child action/resource scopes cannot exceed the parent. A child cannot outlive its parent or exceed its amount/currency ceiling.
- Delegation depth is bounded (default maximum depth: 5).
- Each delegation stores the public key that signed it. Key rotation invalidates delegations signed by the retired key; descendants then fail closed.
- Revocation is signed by the delegator. Revoking an ancestor invalidates descendants at authorization time.
- Participant suspension/revocation invalidates any chain containing that participant.
- A delegation only conveys the stated operational scope. It does not grant treasury ownership, legal authority, or permission to perform a high-risk action.

## Signing

The caller builds the exact canonical JSON payload using `DelegationStore.signing_payload(...)`, serializes it as UTF-8 JSON with sorted keys and compact separators, then signs those bytes with the delegator's Ed25519 private key. The signature is URL-safe base64 without padding. The signing payload includes the policy version, delegation ID, delegator, delegate, action, resource, expiry, optional amount ceiling/currency, parent ID and depth.

For a root delegation, the owner public key must be configured out-of-band as `trusted_roots={owner_participant_id: owner_public_key}`. Do not store private keys in this repository or database. Root trust configuration must come from a protected deployment secret/configuration channel, not from a participant's self-assertion.

For child delegations, the delegator's registered agent public key is used. The child payload must include its parent delegation ID and calculated depth.

## Local API example

```python
from economy.delegation import DelegationStore

store = DelegationStore(
    "./data/participants.sqlite3",
    trusted_roots={OWNER_PARTICIPANT_ID: OWNER_PUBLIC_KEY_BASE64URL},
)
payload = store.signing_payload(
    delegation_id="delegation-001",
    delegator_id=OWNER_PARTICIPANT_ID,
    delegate_id=AGENT_PARTICIPANT_ID,
    action="task:submit",
    resource="project:alpha",
    expires_at="2030-01-01T00:00:00+00:00",
)
# Sign the canonical JSON bytes of payload with the delegator's Ed25519 key.
# Then call store.create(..., **payload_fields, signature=SIGNATURE).
```

Authorization checks the complete stored chain and participant statuses. Revocation signatures cover the exact event payload returned by `DelegationStore.revocation_payload(delegation_id, actor_id)`.

## Important limits

- This is a local SQLite prototype; it is not a network identity or delegation service.
- The trusted-root public-key mapping is injected by the local application and is not yet managed through a hardened owner console. Root-key rotation requires an out-of-band configuration update and re-issuing root delegations.
- SQLite is not tamper-proof. An attacker with database write access may alter stored rows; production must use stronger audit integrity and protected storage.
- The module does not replace the existing high-risk approval gate. Publishing, spending, custody, transfers, contracts, ownership changes and other high-risk actions remain blocked pending a separately verified approval service.
- The current capability CLI still has local-admin semantics and does not authenticate the issuer. Do not expose it to the internet or treat it as production authority.
- No payment, wallet, custody, escrow, or live treasury execution is enabled.
- Ed25519 cryptography is an optional dependency: install with `pip install -e ".[identity,dev]"`.

## Tests

The test suite covers trusted-root enforcement, invalid signatures, narrowed child scopes, parent expiry, amount/currency ceilings and ancestor revocation. Test verifiers are injected in unit tests; production verification uses the Ed25519 verifier.
