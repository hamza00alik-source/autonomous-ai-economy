# Capabilities and Authorization

## Local prototype behavior

The local `CapabilityStore` implements:
- Deny-by-default, exact action/resource grants, and explicit resource wildcard support.
- Optional timezone-aware future expiry.
- Optional amount ceilings that must include a three-letter currency.
- Non-negative amount enforcement; a capped grant cannot be used unless the request supplies an amount and matching currency.
- Revocation by the grant's recorded issuer.
- Participant-status enforcement when the participant registry exists in the same database; missing, suspended or revoked subjects are denied.
- An audit record for each authorization decision.
- High-risk actions always return `require_approval`, even when a capability matches or an approval-reference string is supplied.

The signed delegation module adds a separate bounded chain. It narrows parent scopes and enforces expiry, amount/currency ceilings, participant status, revocation and depth. High-risk delegated actions also return `require_approval`.

## High-risk action classes

Publishing, customer commitments, contract signing, spending, custody, transfers, permission escalation, ownership changes, account connections, financial execution and private-data export are high-risk. A capability or delegation alone never authorizes them.

Service-listing publication has a separate local HMAC approval mechanism bound to the exact listing fingerprint, expiry and single-use nonce. Do not treat this listing-specific mechanism as a universal approval service.

## Example

```bash
economy capability-grant --subject AGENT_ID --issuer OWNER_ID \
  --action task:submit --resource project:demo
economy authorize --subject AGENT_ID --action task:submit --resource project:demo
```

The CLI is local administrative tooling only. The `issuer` field is not authenticated by the CLI; possession of local database/CLI access is not proof of owner authority.

## Production gaps

- No authenticated remote owner/issuer session or owner console.
- No unified policy gateway that composes capability grants, delegation, risk classification and verified owner approvals for every external action.
- The generic `approval_ref` accepted by `CapabilityStore.authorize` is not verified and must never authorize execution.
- Local SQLite is not tamper-proof; audit integrity, secure backups, key rotation and incident recovery need production engineering.
- No live financial or external action execution is enabled.
