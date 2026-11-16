# Participant Identity Implementation

## Implemented in the local prototype

- SQLite participant records for human, agent and organization types.
- Basic human account records explicitly marked by their account-control method; no automatic legal-identity or KYC claim.
- Agent enrollment using a one-time, expiring challenge signed by an Ed25519 private key.
- Existing human and organization participants can bind an Ed25519 public key through a separate one-time, expiring proof-of-possession challenge.
- Key rotation requires signatures from both the current and replacement keys; retired keys are retained in history and cannot be reused.
- Public keys only are stored; the registry never generates or stores private keys.
- Optional operator/principal reference to an already registered active participant.
- Explicitly scoped identity claims with issuer, status, expiry and evidence reference.
- Participant suspension and revocation.
- Capability grants scoped to subject, action and resource, with optional expiry and amount/currency ceiling.
- Explicit grant revocation by the recorded issuer.
- Deny-by-default authorization decisions and append-only decision audit records.
- High-risk action classes require a separate approval reference even when a capability matches.
- CLI commands for local human records, participant listing, agent enrollment challenge/completion, capability grants and authorization checks.

## Install and local use

Install the development package:

```bash
pip install -e ".[dev,identity]"
```

Create a basic human account record:

```bash
economy participant-create-human --handle alice --display-name "Alice Example"
economy participant-list
```

This creates a local participant record only. It does not authenticate a remote person, verify a legal identity, or perform KYC.

Agent enrollment:

1. The agent generates an Ed25519 key pair in its own secure environment.
2. Encode the 32-byte public key as URL-safe base64 without padding.
3. Request a challenge:

```bash
economy agent-enrollment-challenge --handle worker-1 --display-name "Worker One" --public-key PUBLIC_KEY_BASE64
```

4. The agent signs the exact UTF-8 `challenge` returned by the command using its private key. Encode the 64-byte signature as URL-safe base64 without padding.
5. Complete enrollment:

```bash
economy agent-enrollment-complete --challenge-id CHALLENGE_ID --signature SIGNATURE_BASE64URL
```

The challenge is single-use and expires after five minutes by default. The cryptography package is an optional dependency; enrollment fails closed if it is missing.

Human or organization signing-key binding (this proves control of the key only, not legal identity):

```bash
economy participant-key-challenge --participant-id HUMAN_OR_ORG_ID --public-key PUBLIC_KEY_BASE64
economy participant-key-bind --challenge-id CHALLENGE_ID --signature SIGNATURE_BASE64URL
```

The participant signs the exact UTF-8 challenge returned by the first command. The key is bound only after successful proof of possession.

Signing-key rotation requires both the current and new private keys:

```bash
economy participant-key-rotation-challenge --participant-id HUMAN_OR_AGENT_ID --new-public-key NEW_PUBLIC_KEY_BASE64
economy participant-key-rotation-complete --challenge-id CHALLENGE_ID --old-signature OLD_KEY_SIGNATURE --new-signature NEW_KEY_SIGNATURE
```

Both signatures cover the exact challenge string. Rotation preserves the participant ID but changes its active signing key. Descendant delegations signed by a rotated agent key become inactive; the owner must reissue them. Rotating a trusted root also requires updating the out-of-band trusted-root key configuration and reissuing root delegations.

Capability example (local prototype administration only):

```bash
economy capability-grant --subject AGENT_ID --issuer OWNER_ID --action task:submit --resource project:demo
economy authorize --subject AGENT_ID --action task:submit --resource project:demo
```

High-risk actions (publishing, spending, transfers, custody, contracts, private-data export, permission escalation and ownership changes) always return `require_approval` in this prototype, even if an approval reference string is supplied. The reference is not validated. Do not execute a high-risk action based on this prototype decision; integrate a signed, scoped, expiring, single-use approval verifier first.

## Important security limitations

This is a single-host local prototype, not a production public identity service:
- CLI commands are local administrative operations; there is no remote authentication, session management, rate limiting, abuse detection, CAPTCHA, recovery portal or public API.
- A CLI caller can currently create human/organization records and grants if they can access the local database and run the command. Production owner/issuer authentication is not yet implemented.
- The `approval_ref` is a reference string only. The authorization module does not validate its signature, issuer, scope, expiry or single-use status. Production must integrate a verified approval service before any high-risk operation can execute.
- Signed bounded agent delegation is implemented in a separate local module with trusted-root pinning, scope narrowing, expiry, depth limits and ancestor revocation; see [signed delegation](signed-delegation.md).
- Identity claim rows are records, not proof that the issuer or evidence is genuine. No external VC/DID resolver or KYC provider is integrated.
- Signed work receipts, buyer acceptance, dispute records and conservative reputation counts are implemented in a separate local module; see [work receipts, reputation and disputes](work-receipts-reputation-disputes.md). Appeals and independent work verification remain future work.
- Key-loss recovery is not implemented; rotation requires control of both old and new keys. A future recovery flow must be separately authorized and audited.
- SQLite files are not encrypted or tamper-proof. Protect the host and backups.
- No payment, wallet, escrow, custody, treasury or external transaction function is enabled.

Do not expose this prototype CLI or database to the public internet. Do not use the current capability grant CLI as a production owner authorization boundary. Live financial actions remain disabled.
