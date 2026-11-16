# Owner approval controls

## Signed approval tokens

The opportunity-to-listing pipeline no longer accepts a plain `owner_approved=True` flag. It requires a signed, expiring, single-use token bound to the exact opportunity fields and evidence.

- The owner creates a token only after reviewing the opportunity and explicitly deciding to authorize product drafting.
- Tokens use HMAC-SHA256 and require a secret of at least 32 bytes.
- Tokens expire after 10 minutes by default (configurable up to one hour).
- The token is bound to a SHA-256 fingerprint of the opportunity, including every evidence item. Editing the opportunity invalidates the token.
- A local SQLite store records consumed nonces and rejects replay.
- The token and secret must never be committed, logged, or shared publicly.

## Local setup

Generate a secret locally:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Store it in the local `.env` file as `ECONOMY_OWNER_APPROVAL_SECRET`. The repository ignores `.env` and SQLite state files. Do not paste the secret into chat or GitHub.

The application currently exposes token creation as a Python API so the approval action remains explicit and local:

```python
import os
from economy.approvals import create_approval_token
from economy.business_pipeline import OpportunityToListingPipeline

# Load an Opportunity that has already passed evidence validation.
secret = os.environ["ECONOMY_OWNER_APPROVAL_SECRET"]
token = create_approval_token(opportunity, secret)  # run only after owner review
result = OpportunityToListingPipeline().run(
    opportunity,
    approval_token=token,
    approval_secret=secret,
)
```

The example assumes `opportunity` is the reviewed `Opportunity` instance. Token creation is itself the explicit approval act; do not call it automatically from an agent.

## Security limitations

This is a local prototype control, not a complete identity or production authorization system. Anyone who obtains the secret can create approvals. The SQLite replay store is local to one installation and is not shared across machines; losing or rolling back that database can weaken replay protection. There is no remote owner login, hardware-backed key, multi-party approval, tamper-evident audit log, or external key management yet. Keep the approval store on persistent private storage and protect the device and secret.

A valid token only authorizes product-draft creation in this workflow. It does not authorize publishing, customer contact, spending, contracts, payment processing, custody, or blockchain transfers. Those remain disabled and require separate controls and explicit approval.
