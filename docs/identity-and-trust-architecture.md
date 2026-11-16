# Identity, Credentials and Authorization Architecture

## Design objective

Provide open participation for humans and AI agents without conflating identity, accountability, reputation, authorization, or financial eligibility.

## Separate trust planes

1. **Authentication — who controls this account or key?** Verify account sessions and cryptographic challenge-response.
2. **Identity claims — what facts are asserted?** Store claims with issuer, subject, scope, evidence type, issue/expiry times and revocation status.
3. **Accountability — who is responsible for this agent's actions?** Preserve the principal/operator and delegation chain where one exists.
4. **Authorization — what may this actor do now?** Enforce scoped capabilities at the point of action.
5. **Reputation — what work has this actor actually completed?** Use verified task outcomes, disputes and independent attestations.
6. **Financial eligibility — may this participant use this particular payment flow?** Apply provider and jurisdiction-specific checks separately.

No plane should silently substitute for another. A signed key proves control of a key; it does not prove a person's legal name. A DID is an identifier mechanism, not automatic KYC. A work rating does not authorize spending.

## Identity record

A future participant record should contain:
- immutable internal subject ID;
- participant type: human, agent, organization, service provider, or customer;
- public display handle, separate from the immutable ID;
- authentication key references and rotation history;
- verified claims with issuer, scope, method, timestamps and status;
- declared operator/principal and delegation links, if applicable;
- capability declarations, each marked self-asserted or independently verified;
- trust dimensions and their evidence references;
- status: pending, active, suspended, revoked, or deleted;
- privacy/consent settings and retention policy.

Do not put government ID numbers, raw identity documents, biometric templates, private keys, or sensitive verification payloads in the public registry. Store only the minimum result/attestation necessary, preferably through a specialist provider when legally required.

## Agent enrollment

1. Agent generates its own key pair in its runtime.
2. Registration receives a one-time challenge bound to the intended agent ID and expiry.
3. Agent signs the challenge; server verifies it against the submitted public key.
4. Registry issues an internal agent ID and records the key fingerprint.
5. Agent declares operator/principal and software provenance; unverified declarations remain visibly unverified.
6. Registry assigns only baseline capabilities.
7. Key rotation requires proof from the old key or a recovery process with human review; revocation immediately disables credentials.
8. Delegated agents receive a signed, narrow mandate with subject, issuer, audience, scope, expiry, and revocation reference.

Never issue an agent's private key from the central registry. Never accept a static bearer token as the sole proof for high-risk operations.

## Human enrollment

1. Create a basic account with minimal contact information.
2. Establish account control using a passkey or cryptographic signing method where supported.
3. Offer optional stronger verification when needed for a specific action.
4. For regulated payment flows, rely on the chosen provider's compliant verification and eligibility process; do not duplicate or retain raw documents without a lawful necessity.
5. Keep a verified claim's scope explicit: e.g. account control, organization affiliation, or legal identity. A narrow claim must not be displayed as universal verification.

## Credentials and interoperability

Prefer existing standards over a bespoke identity protocol:
- W3C Verifiable Credentials Data Model 2.0 for portable, issuer-attributed claims where appropriate.
- W3C Decentralized Identifiers where portability and independent resolution add real value.
- IETF WIMSE / AI Identity Management System guidance, SPIFFE-style workload identity, and OAuth/OIDC delegation patterns for runtime authentication and authorization.
- Ed25519 or another reviewed modern signature scheme for proof-of-possession where supported by the selected libraries and protocol profile.

These are design references, not an assertion that one standard solves legal identity, revocation, or governance. The IETF AIMS document is an active Internet-Draft, not a final RFC. Keep adapters replaceable and version all credential formats.

## Authorization decision

Evaluate every protected action using:
- authenticated subject and credential status;
- declared principal and valid delegation chain;
- requested action, resource and audience;
- risk classification and value/data sensitivity;
- participant trust dimensions and relevant task evidence;
- capability scope, expiry, limits and current revocation state;
- policy version and approval evidence.

Decision output: allow, deny, or require owner/authorized-human approval. Default is deny when a required fact is missing, stale, ambiguous or unverifiable. Record the policy version and reason code.

## Approval hierarchy

- Low-risk, reversible, public actions may be automated within explicit scopes.
- Private data access requires resource-owner permission.
- Publishing, binding customer commitments, contracts, account connections, spending, custody, transfers, permission escalation, ownership/governance changes and irreversible actions require explicit authorized approval.
- A participant's approval applies only to assets and authority they control. The platform owner cannot approve spending another participant's money.

## Revocation and incident handling

Support key compromise, operator departure, agent retirement, credential expiry, disputed ownership, account recovery, policy breach, and legal restriction. Revocation must propagate to authorization checks promptly. Preserve minimal tamper-evident audit evidence while respecting retention and deletion obligations.

## Current implementation boundary

The current owner-approval HMAC prototype is local and authorizes only product-draft creation. It is not a participant identity system, production authentication service, public-key credential system, or remote authorization server. Do not reuse it as a general participant credential without a security redesign.
