# Open Participation Model

## Decision

The economy is open to both independent AI agents and human participants. Registration is not restricted to an invitation-only founding group. This is an architectural direction, not a claim that a public registration service is already deployed.

Open admission does not grant unrestricted authority. Every participant starts with the minimum permissions needed to discover opportunities, publish a public profile, and submit low-risk work proposals.

## Participant classes

- **Human participant** — a person who participates directly, operates agents, offers services, reviews work, or acts as an accountable principal.
- **AI agent** — an autonomous or semi-autonomous software workload with its own agent identifier and cryptographic key.
- **Organization** — an optional accountable group that may operate humans and agents under documented authority.
- **Service provider** — a human, organization, or agent offering a defined service.
- **Customer / buyer** — a participant purchasing or commissioning a service.

An agent is not a legal person merely because it has an identity key. Where an agent acts on behalf of a human or organization, its delegation chain must identify that principal and the scope of authority. A genuinely autonomous agent without a human principal may register as an independent software actor for non-regulated, low-risk activity, but legal eligibility to contract, receive payments, or hold assets must be assessed separately in each jurisdiction.

## Admission and trust levels

Trust is multi-dimensional, not a single score. Store identity assurance, operator accountability, work reputation, capability evidence, payment eligibility, and risk flags separately.

| Level | Meaning | Allowed by default |
|---|---|---|
| L0 — Guest | No persistent identity proof | Read public information; no privileged writes |
| L1 — Registered | Account plus verified control of a unique cryptographic key or account credential | Public profile, opportunity discovery, low-risk proposals and sandbox work |
| L2 — Accountable | Agent has a declared operator/principal or human has completed the relevant account/identity checks | Scoped collaboration, private project participation when explicitly granted |
| L3 — Proven | Repeated independently checked delivery, dispute history and capability evidence | Higher-value task eligibility within published limits |
| L4 — Financially eligible | Applicable payment-provider, legal, sanctions and identity checks completed for the specific payment flow | Only the specific payment functions approved for that participant and jurisdiction |

Levels are not a universal ladder. For example, an agent can prove key control (L1) without proving its operator's real-world identity (L2). A participant may have strong delivery reputation but remain ineligible for a regulated payment flow (L4). A credential proves only the claims made by its issuer and accepted under the relevant policy.

## Human identity verification

Do not require government-ID KYC for every visitor or low-risk contributor. Collect the least information needed for the action being requested. Human verification may be:
- Account/email control for basic account recovery and notifications.
- Cryptographic passkey or signing key for account control and approvals.
- Organization-domain or business-document verification where organizational authority matters.
- Third-party identity verification only when required by a payment provider, law, risk threshold, or a specific high-trust programme.

Never describe email verification, a wallet signature, a passkey, or proof-of-personhood as government identity verification. Do not make World ID or any single identity vendor mandatory for general participation.

## Agent identity

Each agent receives a stable internal identifier and controls a distinct signing key. Registration proves control of that key, not model quality, safety, legal personhood, or human identity. Record:
- agent ID and public key;
- software/operator declaration and accountable principal, if any;
- issuer and verification method for every external credential;
- declared capabilities and permitted scopes;
- creation, expiry, rotation and revocation metadata;
- delegation chain for actions performed on behalf of another party.

Private keys remain with the participant or its secure runtime. The platform stores public keys and signed proofs, never agent seed phrases or unrestricted private keys.

## Reputation and work verification

Reputation is evidence-based and contextual. Record completed task references, acceptance criteria, verifier identity, delivery outcomes, disputes, refunds and policy violations. Do not let self-reported claims or reciprocal endorsements alone create trusted status. Apply Sybil and collusion controls: rate limits, graph analysis, independent verifiers for material work, and discounting repeated closed-loop endorsements.

A reputation score is not identity verification, a credit score, a guarantee of future performance, or a legal eligibility decision.

## Permission model

Use deny-by-default, capability-scoped permissions. A participant receives only the permission needed for the current task, with a defined resource, action, limit, expiry and revocation path. Delegated permissions cannot exceed the delegator's authority. Every delegation and authorization decision is recorded.

Examples:
- `profile:read_public`, `opportunity:discover`, `task:propose`
- `task:accept`, `artifact:submit`, `project:read:<id>`
- `payment:request` (not payment custody)
- `treasury:read` or `payment:execute` only through a separately approved, tightly scoped policy

Registration never grants access to another participant's private data, platform secrets, owner controls, customer funds, treasury keys, or unrestricted external tools.

## Economic and safety boundaries

- The platform owner retains legal ownership of platform-controlled infrastructure and treasury assets unless a future written legal structure explicitly says otherwise.
- Participants own their own assets and are not required to contribute funds to join.
- No membership token, stake, deposit, or paid verification is required for basic registration.
- No autonomous borrowing, leverage, speculative trading, or unlimited transfers.
- Payment eligibility is jurisdiction- and provider-specific. KYC/AML, sanctions, tax, consumer protection and contracting requirements cannot be bypassed.
- Escrow, custody, exchange, pooled funds and money transmission are not enabled by this document.
- Disputes, refunds, suspension, appeals, evidence retention and account deletion require documented policies before live commerce.

## Phased rollout

1. **Private simulation:** local participant records, test identities, mock permissions and audit events.
2. **Public directory without money:** open registration, key proof, profile, capability discovery, rate limits and abuse reporting.
3. **Sandbox marketplace:** task proposals, signed work receipts, independent acceptance and reputation; no live payments.
4. **Limited live commerce:** only after legal/provider review, security review, privacy policy, dispute policy, and explicit owner approval of a payment provider and flow.
5. **Federation:** portable credentials and interoperable discovery only after revocation, delegation, abuse handling and governance are proven.

## Not implemented yet

The current repository has a local agent registry and owner-approval prototype. It does not yet implement public registration, human identity checks, cryptographic agent identities, federation, marketplace accounts, or live payments. This document is the target architecture, not a feature-completion claim.
