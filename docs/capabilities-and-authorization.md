# Capabilities and Authorization

## Local prototype behavior

The local `CapabilityStore` implements:
- Deny-by-default, exact action/resource grants, and explicit resource wildcard support.
- Optional timezone-aware future expiry.
- Optional amount ceilings that must include a three-letter currency.
- Non-negative amount enforcement; a capped grant cannot be used unless the request supplies an amount and matching currency.
- Revocation by the grant's recorded issuer.
- Fail-closed participant-status enforcement: the participant registry must exist in the same database, and missing, suspended or revoked subjects are denied.
- An audit record for each authorization decision.
- High-risk actions always return `require_approval`, even when a capability matches or an approval-reference string is supplied.

The signed delegation module adds a separate bounded chain. It narrows parent scopes and enforces expiry, amount/currency ceilings, participant status, revocation and depth. High-risk delegated actions also return `require_approval`.

The local `PolicyEngine` composes either a capability grant or signed delegation with `ActionApprovalStore`. For high-risk actions it requires a short-lived HMAC approval bound to the exact subject, action, resource, amount and currency, consumes the nonce once, and records the final decision. An `allow` result means policy checks passed; it does not execute the requested action.

## High-risk action classes

Publishing, customer commitments, contract signing, spending, custody, transfers, permission escalation, ownership changes, account connections, financial execution and private-data export are high-risk. A capability or delegation alone never authorizes them.

Service-listing publication has a separate local HMAC approval mechanism bound to the exact listing fingerprint, expiry and single-use nonce. The generic action-approval secret and catalog-approval secret are separate purpose-bound credentials.

## Example

```bash
economy capability-grant --subject AGENT_ID --issuer OWNER_ID \
  --action task:submit --resource project:demo
economy authorize --subject AGENT_ID --action task:submit --resource project:demo
```

The CLI is local administrative tooling only. The `issuer` field is not authenticated by the CLI; possession of local database/CLI access is not proof of owner authority.


## Local PolicyEngine example

```python
from economy.permissions import CapabilityStore
from economy.policy import ActionApprovalStore, PolicyEngine

capabilities = CapabilityStore("./data/participants.sqlite3")
approvals = ActionApprovalStore("./data/participants.sqlite3")
engine = PolicyEngine(
    capabilities, approvals,
    approval_secret=ACTION_APPROVAL_SECRET,
)
# Create this token only after the owner has explicitly reviewed and approved
# the exact subject/action/resource/amount/currency request.
owner_approved_token = ActionApprovalStore.create_token(
    AGENT_ID, "spend", "treasury:main", ACTION_APPROVAL_SECRET,
    amount_minor=250, currency="USD",
)
decision = engine.authorize(
    AGENT_ID, "spend", "treasury:main",
    amount_minor=250, currency="USD",
    approval_token=owner_approved_token,
)
# "allow" is an authorization decision only; it does not execute a transfer.
```

The token must be created only after the owner explicitly approves the exact action request. Configure `ECONOMY_ACTION_APPROVAL_SECRET` as a separate random secret of at least 32 bytes. Do not reuse the opportunity or catalog approval secret.

## Production gaps

- No authenticated remote owner/issuer session or owner console.
- No production external-action gateway, authenticated owner console or integration with external execution adapters.
- The generic `approval_ref` accepted by `CapabilityStore.authorize` is not verified and must never authorize execution; use `PolicyEngine` for local decision composition.
- Local SQLite is not tamper-proof; audit integrity, secure backups, key rotation and incident recovery need production engineering.
- No live financial or external action execution is enabled.
