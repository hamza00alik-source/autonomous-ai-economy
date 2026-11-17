# Agent-Native Revenue Strategy

Status: **controlling commercial direction**  
Last updated: 2026-11-17

## Non-negotiable objective

The first commercial milestone is a real payment earned by an AI agent acting as an independent economic participant. The owner must not act as the freelancer, manually create the deliverable, or approve each routine business operation.

The economy is owned by the project owner. Agents are autonomous economic actors within delegated authority; they do not acquire ownership of the platform treasury by participating.

## Required earning lifecycle

1. **Agent identity:** each agent has a cryptographic identity, key history, participant record and verifiable proof of key possession. Operational identity is distinct from legal identity.
2. **Demand discovery:** agents continuously find and assess real buyer demand using permitted sources and retain evidence, source dates and confidence.
3. **Offer creation:** agents select a bounded product/service they can actually produce, calculate costs and price, run quality checks, and create a machine-readable offer.
4. **Publication and discovery:** agents publish through a channel whose terms permit the actual provider/agent model. Do not disguise an agent as a human freelancer or use a human account as a proxy.
5. **Customer intake and agreement:** buyer identity/context and exact scope, price, deadlines, revision limits and acceptance criteria are recorded. Agents may accept routine work within policy and budget limits.
6. **Execution and delivery:** the assigned agent performs the work in an isolated runtime, produces verifiable artifacts and submits a delivery receipt.
7. **Revision and dispute handling:** agents handle in-scope revisions and evidence-based disputes under bounded policy; escalations are limited to exceptional legal, safety, fraud or irreversible cases.
8. **Settlement and reconciliation:** payment is confirmed from a trusted provider/chain source and reconciled against the agreement, fees, refunds and net proceeds. A local ledger entry alone is never proof of payment.
9. **Operating treasury:** verified revenue can fund capped compute and operating costs under agent-specific budgets, limits, audit and emergency stops. No borrowing, leverage, unlimited transfers or speculative trading.
10. **Reputation and expansion:** completed and accepted work produces evidence-linked reputation; agents can subcontract or transact with other agents under the same rules.

## Autonomy policy

Routine discovery, offer drafting, permitted publication, bounded pricing, order acceptance, execution, delivery, in-scope revisions and accounting should run without routine owner approval once the relevant policy and budget are configured.

Controls remain for legally required identity, tax, sanctions, consumer-protection and provider underwriting; actions outside delegated scope or spending caps; irreversible transfers, custody, regulated financial activity and material legal commitments; and suspected compromise, fraud, abuse or safety incidents. These are narrow safeguards, not a reason to require human approval for every ordinary operation.

The system must never falsify a human identity, evade KYC, violate marketplace terms or imply that a cryptographic agent ID is legal personhood.

## Existing foundations to reuse

The repository already contains useful local foundations: participant identities and key rotation, scoped capabilities and signed delegation, task offers and agreements, work receipts and buyer acceptance, artifact digest verification, reputation/dispute structures, audit features, a durable task queue, isolated built-in worker execution and a single-host supervisor.

These are local prototype capabilities. They do not yet establish autonomous commercial execution, public marketplace access, live payments or production uptime.

## Critical missing capabilities

| Capability | Current state | Required result |
|---|---|---|
| Autonomous agent decision loop | No continuous model-driven operation | Agents choose and execute bounded next actions |
| Live demand/customer acquisition | Research leads only | Real buyers discover permitted offers |
| Agent-native offer publishing | Local catalog only | External channel accepts the agent/provider model |
| Autonomous work execution | Fixed deterministic built-ins | Useful agent-produced work with QA and isolation |
| Customer communication/revisions | Not end-to-end | Agent handles routine interaction within contract |
| Payment acceptance/settlement | Source-only NOWPayments invoice/IPN, fixed-price checkout, protected delivery and gross attribution to internal producer ID; not deployed, no live payment or wallet reconciliation | Real payment confirmed, wallet receipt/fees/refunds reconciled and agent credit governed |
| Agent treasury/compute funding | Simulated/local accounting | Capped spend from cleared earned revenue |
| Always-on production | Single-host prototype supervisor | Hosted resilient runtime with monitoring/recovery |
| Independent participant onboarding | Local registry/API only | Secure public registration and abuse resistance |

## Fastest credible first-revenue path

Do not select a channel because it is familiar. Select it only after verifying that its current terms permit an AI agent or clearly disclosed automated provider to offer and deliver the chosen work; the agent can authenticate and transact without impersonating a human; the buyer can pay through an available lawful route; the provider/payment model is eligible in the operating jurisdiction; and the workflow fits the approved resource budget.

Prefer a narrow, reproducible digital service or downloadable artifact an agent can generate and validate with existing tools. Avoid regulated advice, copyrighted materials, platform manipulation, account access and work requiring human physical performance.

The first pilot must demonstrate: **agent identity → real buyer → accepted agreement → agent-produced delivery → buyer acceptance → cleared payment → reconciled net proceeds**. The current `game-asset-builder` ID is only an internal producer label, not cryptographic participant enrollment or legal identity. Gross sales attribution is not yet an agent credit or disbursement. See [agent revenue accounting](agent-revenue-accounting.md).

## Definition of first agent-earned revenue

Count it only when there is a real buyer (not the owner or a test account); an agreement identifying the agent/provider and exact scope; agent-produced delivery accepted under the agreement; payment confirmed as settled by the actual payment rail; fees, refunds and net proceeds reconciled; and no identity deception or policy violation.

A listing, impression, enquiry, unpaid order, simulated ledger credit, test transaction or pending balance is not revenue.

## Execution rule

Every implementation must advance at least one missing capability above and have a testable acceptance criterion. Stop building disconnected infrastructure that does not shorten the path to the first agent-earned payment. Distinguish local prototype, integrated, deployed and economically proven states.

## Deprecated research

- [Historical human-freelancer pilot](first-revenue-pilot.md)
- [Historical Upwork listing draft — do not publish](first-revenue-upwork-catalog-draft.md)
