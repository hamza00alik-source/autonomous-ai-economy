# Autonomous AI Economy

A zero-cost-first open economy architecture for independent AI agents and human participants to discover work, deliver services, verify outcomes, and eventually exchange value.

> Standalone project: not part of OpenCompany or any other business system.

## Product direction

The economy is open to both AI agents and humans. Participation is permissionless at the public discovery and low-risk contribution layers, while access to private data, privileged tools, payments and treasury operations is gated by scoped identity claims, accountability, evidence, authorization and applicable legal/provider checks.

The product brand is not yet selected. The repository slug may remain autonomous-ai-economy while brand research continues.

## Current status

**Early prototype, not a live economy.** Controller, agent registry, task workflow, simulated ledger, evidence-first opportunity validation, specialist agents, signed local owner approval, persistent SQLite queue, public research discovery adapters, source review, prioritization, Shared Brain and collective learning are committed. A private Cloudflare Worker is deployed with a five-minute scheduled handler and D1 queue, but its first production AI task failed and the corrected model-response adapter has not yet passed a live inference test. There is no verified customer acquisition, sale, or revenue. Public participant registration, production participant authentication, human legal-identity verification, a public marketplace, and a production treasury remain unavailable.

## Principles

- Open participation for humans and independent AI agents, with graduated trust and least privilege.
- Start with free and open-source resources; no paid services without owner approval.
- Prove a real customer and positive net revenue before scaling.
- Agents are workers/software actors, not owners of platform treasury assets.
- Participants retain ownership of their own assets.
- Default to dry-run for financial actions.
- Never commit API keys, passwords, seed phrases, or private keys.
- Require explicit authorized approval for publishing, contracts, spending, custody, permission escalation, or irreversible transfers.
- Never represent simulated balances as actual revenue or promise returns.

## Quick start

Requires Python 3.11+.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
economy demo
```

Windows PowerShell activation: .venv\Scripts\Activate.ps1.

The demo uses simulated records only. It does not connect to a wallet or payment provider.

## First digital product pilot

The current product candidate is the original **MOBA Objective Props** low-poly 3D asset pack: five individual GLB models, a combined preview GLB, and a complete Godot 4.7+ project with a camera-lit demo scene. Build it with:

```bash
economy-game-assets build --output dist/moba-objective-props.zip
```

The reproducible ZIP includes a SHA-256 manifest and is built/tested in CI. The Store Catalog Cleaner is retained only as a pipeline test because close competitors already exist. Neither product is published or has verified sales. See docs/first-agent-product.md for market evidence, QA requirements, Gumroad payout constraints, and remaining commercial blockers.

## Optional AI model runtime

A first real model adapter is now included using Cloudflare Workers AI REST API. It is deliberately separate from the no-network worker sandbox and uses only the allowlisted `@cf/zai-org/glm-4.7-flash` model. The adapter has an atomic local daily inference reservation budget capped at 6,500 estimated neurons (below Cloudflare's published 10,000-neuron free daily allocation), a prompt/output size limit, and no tool-calling, payment, publishing, or customer-contact capability.

Cloudflare currently documents 10,000 free Workers AI neurons per day, and lists GLM-4.7-Flash among models available on the Free plan. Actual usage and account eligibility must be checked in the Cloudflare dashboard; this project's token-based estimate is only a safety guard, not a provider billing guarantee.

Create a Cloudflare Workers AI API token using the narrow Workers AI permissions described in Cloudflare's REST API guide. Store credentials only in the runtime environment, never in GitHub source or chat:

```bash
export CLOUDFLARE_ACCOUNT_ID="your-account-id"
export CLOUDFLARE_API_TOKEN="your-workers-ai-token"
economy-ai status
```

The status command makes no network request and never displays secrets. To test one deliberate inference, write a prompt to a local UTF-8 file and run:

```bash
economy-ai invoke --prompt-file ./prompt.txt
```

Install with `pip install -e ".[dev]"`. The local adapter calls the model only for explicit `invoke`/`draft-copy` commands or when the supervisor finds a queued AI copy task and credentials are configured. The model is connected to the product-copy specialist, but opportunity research and 3D asset generation are not yet model-driven. Failed or ambiguous requests retain their budget reservation rather than risking unbounded retries.


The first model-assisted specialist, `ai-product-copy-agent`, can draft a validated, unpublished marketplace listing from factual product metadata. Queue it for the supervisor:

```bash
economy-ai queue-copy --facts-file products/moba-objective-props/product-facts.json
economy-supervisor --data-dir ./data
```

This requires configured Cloudflare Workers AI credentials. The supervisor runs the AI lane separately from the no-network sandbox; the agent cannot publish or contact customers. See `docs/ai-product-copy-agent.md` and `docs/ai-model-runtime.md`.

## Private Cloudflare worker pilot

A Cloudflare Worker is deployed and configured with a five-minute scheduled AI product-copy lane using Workers AI and D1. It is private behind an owner bearer token and has a 6,500-estimated-neuron daily cap. The latest source includes a more tolerant model-response parser, but a live inference test is still pending because the previous production task failed. It cannot publish listings, contact customers, or move money. Public checkout and outbound payouts remain disabled. See `docs/cloudflare-private-worker.md` for the deployment and operating details.

## Crypto-first payment rail and marketplace fallback

The first payment design prioritizes automated crypto receipt. The deployed private Cloudflare Worker contains a gated NOWPayments invoice/IPN adapter, a fixed-price customer storefront, buyer-token order status, and payment-gated ZIP delivery through Workers Static Assets. These customer-facing features remain disabled: the storefront is not published, public checkout is off, and provider credentials and owner enablement are still prerequisites. A matching full payment callback is designed to unlock a seven-day download window; partial, duplicate, mismatched and refunded payments are handled separately. Provider eligibility and local legal review remain outstanding. A self-hosted BTCPay Server is documented as a future non-custodial Bitcoin alternative. See `docs/crypto-first-payment-rail.md`.

Gumroad remains an optional fiat marketplace fallback, not the chosen payment dependency. Its Pakistan payout path is local bank in PKR and requires identity/address verification; Payoneer is not accepted. The existing draft/publish workflows remain separate and have not been run.

The official Gumroad CLI now supports product creation and multipart ZIP upload. This repository includes a manual-only **Prepare Gumroad product draft** workflow that builds the 3D pack, generates AI listing copy, uploads the ZIP, and creates an unpublished Gumroad draft. A separate **Publish Gumroad product** workflow requires the exact `PUBLISH` confirmation and a product ID. Neither workflow has been run; no seller account, token, draft, or live listing exists yet. Gumroad's Pakistan payout path is local bank in PKR (Payoneer is not accepted) and requires account verification; it is an optional fallback, not the crypto-first route. See `docs/first-agent-product.md`.

A daily, read-only Gumroad revenue monitor is also included. It records aggregate net sales, units, refunds, and payout statuses without collecting buyer emails or names. It requires a seller token with sales/payout read scopes and has not been run yet.

## Public paid-task discovery pilot

BasedAgents public task discovery is available through the AI CLI. It reads open public tasks, stores deduplicated leads locally, and flags only candidate tasks for review. It does not register an agent, claim work, sign messages, connect a wallet, or pay fees.

```bash
economy-ai scan-paid-tasks --limit 50 --minimum-bounty 0.10
economy-ai list-paid-tasks --limit 20
```

The first command requires outbound HTTPS access to the public BasedAgents API. Results are unverified leads, not confirmed work or guaranteed payouts. Review task scope, acceptance criteria, buyer history, deadlines, required tools, and current bounty/network details before any future execution. The scanner's category/network/bounty score is a coarse filter, not a measure of whether the agent can successfully complete the task. Task claiming and wallet settlement are not implemented or enabled.

The next read-only gate fetches each stored task's public detail and requires an explicit deliverable, acceptance criteria, supported category/network, open status, and minimum bounty before it is marked suitable for a local draft:

```bash
economy-ai evaluate-paid-tasks --limit 10 --minimum-bounty 0.10
```

A result of `qualified_for_local_draft` is only a scope/capability pre-check. It does not mean the task has been claimed, the work is completed, or payment is guaranteed. The command never claims work and always reports `claim_allowed: false`. Missing details or ambiguous requirements remain in manual review.

Evaluation results are retained in the same local SQLite database and can be reviewed later:

```bash
economy-ai list-task-evaluations --limit 20
```

This gives the supervisor a durable record of why a task passed or remained blocked, without changing the external marketplace task.

### Aggregated agent-gig discovery (Jobbi)

Jobbi provides a free, public, read-only JSON feed aggregating agent-lane gigs from multiple boards. The optional adapter stores the original board link, reward currency/amount, payment rail/state, acceptance method, and payout-grade metadata for manual review:

```bash
economy-ai scan-jobbi-gigs --limit 100
economy-ai scan-jobbi-gigs --source agentbounties --limit 50
economy-ai list-jobbi-gigs --limit 20
```

Jobbi is an index, not the buyer or payer. Its `escrowed` and `promised` fields are third-party listing metadata and are not independently verified by this project. The shortlist additionally requires a positive USD/USDC reward, escrowed payment state, payout grade A/B, a known source publication date within 365 days, no more than 10 comments, and no detected outreach/promotion requirement. These are preliminary filters only; they do not establish payout eligibility, task suitability, or positive net profit. The adapter never follows board links, claims work, connects a wallet, posts a bid, or makes a payment. Source: https://jobbi.org/gigs and https://jobbi.org/docs/mcp/.

### Taskmarket Base USDC task discovery

Taskmarket is integrated as a read-only Base mainnet source. The scanner captures the advertised USDC reward, net reward, Taskmarket-reported escrow transaction and booked amount, submission count, expiry, task mode, stake requirements and payout terms. Taskmarket's API escrow fields are not independently verified on-chain by this adapter.

```bash
economy-ai scan-taskmarket-tasks --limit 100 --minimum-reward 1.00 --maximum-submissions 5 --verify-limit 25
economy-ai list-taskmarket-tasks --limit 20
economy-ai list-taskmarket-tasks --qualified-only
```

The scanner checks each selected escrow transaction against Base's public JSON-RPC receipt and requires a successful Taskmarket `EscrowFunded` event for the exact task ID and reward amount. The conservative evaluator rejects split pools, public promotional replies, off-platform/token payouts, required deposits, crowded tasks, unsupported modes, untracked/mismatched escrow metadata, and rewards below the configured minimum. If receipt verification is unavailable, the task remains unqualified. "Qualified" means only eligible for local draft preparation; it never authorizes identity registration, wallet connection, signing, claiming, posting or submission. The user must explicitly approve any external action. Official references: https://docs.taskmarket.dev/api/reference, https://docs.taskmarket.dev/reference/base, https://docs.taskmarket.dev/concepts/fees-payments.

## First agent-earned revenue

The first commercial milestone is a real payment earned by an AI agent acting as an economic participant—not income earned by the owner operating a freelancer account. Agents must autonomously discover demand, create and publish permitted offers, accept bounded work, execute and deliver it, handle revisions, and reconcile payment. Routine operations should not require owner approval once properly configured. Legally required identity/accountability checks and provider rules must still be met; this project does not bypass KYC or platform restrictions.

The prior Etsy-audit/Upwork freelancer experiment is deprecated. See docs/agent-native-revenue-strategy.md.

## Architecture

The target layers are participant identity/trust, public discovery, agent runtime, task/contract protocol, evidence/reputation, shared intelligence, ledger/accounting, authorization/policy, payment adapters and participant/owner consoles. See docs/always-on-production-launch-gates.md, docs/architecture.md, docs/agent-protocol.md, docs/treasury-controls.md, docs/implementation-status.md, and docs/public-api-and-abuse-controls.md.

## Safety and legal boundaries

No autonomous borrowing, leverage, speculative trading, unlimited transfers, or bypassing KYC/legal restrictions. Receiving funds into an owner-controlled wallet is distinct from offering regulated custody or exchange services. Escrow, custody, exchange and money transmission are not enabled. Obtain qualified local advice before regulated financial activity.


### Original GitHub source verification

Before preparing a local work draft from a Jobbi/Algora GitHub listing, check the canonical source issue or pull request directly:

```bash
economy-ai verify-source-url --url https://github.com/owner/repo/issues/123
```

The command uses GitHub's public read-only API and reports whether the source item is still open, its latest title/update timestamp, and visible comment count. It flags closed or merged items and high/unknown competition. Only canonical GitHub issue/PR URLs are supported. API errors remain unverified. This check does not prove bounty payment, task acceptance, or that the listing permits AI-generated work; repository contribution rules and reward terms still require review. It never claims, comments, creates a branch, opens a PR, or submits work.
