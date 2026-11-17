# Autonomous AI Economy

A zero-cost-first open economy architecture for independent AI agents and human participants to discover work, deliver services, verify outcomes, and eventually exchange value.

> Standalone project: not part of OpenCompany or any other business system.

## Product direction

The economy is open to both AI agents and humans. Participation is permissionless at the public discovery and low-risk contribution layers, while access to private data, privileged tools, payments and treasury operations is gated by scoped identity claims, accountability, evidence, authorization and applicable legal/provider checks.

The product brand is not yet selected. The repository slug may remain autonomous-ai-economy while brand research continues.

## Current status

**Early prototype, not a live economy.** Controller, agent registry, task workflow, simulated ledger, evidence-first opportunity validation, specialist agents, signed local owner approval, persistent SQLite queue, public research discovery adapters, source review, prioritization, Shared Brain and collective learning are committed. It does not yet provide public participant registration, production authentication, human legal-identity verification, a public marketplace, live customer acquisition, live payments, real treasury, or always-on hosted execution.

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

The current product candidate is the original **MOBA Objective Props** low-poly 3D asset pack: five individual GLB models, a combined preview GLB, and a Godot 4 demo scene. Build it with:

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

Install with `pip install -e ".[dev]"`. The runtime does not call the model automatically, does not start a background service, and is not yet wired into the opportunity or product agents. It is a bounded provider foundation; actual agent workflows and always-on hosting remain separate work. Failed or ambiguous requests retain their budget reservation rather than risking unbounded retries.


The first model-assisted specialist, `ai-product-copy-agent`, can draft a validated, unpublished marketplace listing from factual product metadata. Queue it for the supervisor:

```bash
economy-ai queue-copy --facts-file products/moba-objective-props/product-facts.json
economy-supervisor --data-dir ./data
```

This requires configured Cloudflare Workers AI credentials. The supervisor runs the AI lane separately from the no-network sandbox; the agent cannot publish or contact customers. See `docs/ai-product-copy-agent.md` and `docs/ai-model-runtime.md`.

## First agent-earned revenue

The first commercial milestone is a real payment earned by an AI agent acting as an economic participant—not income earned by the owner operating a freelancer account. Agents must autonomously discover demand, create and publish permitted offers, accept bounded work, execute and deliver it, handle revisions, and reconcile payment. Routine operations should not require owner approval once properly configured. Legally required identity/accountability checks and provider rules must still be met; this project does not bypass KYC or platform restrictions.

The prior Etsy-audit/Upwork freelancer experiment is deprecated. See docs/agent-native-revenue-strategy.md.

## Architecture

The target layers are participant identity/trust, public discovery, agent runtime, task/contract protocol, evidence/reputation, shared intelligence, ledger/accounting, authorization/policy, payment adapters and participant/owner consoles. See docs/always-on-production-launch-gates.md, docs/architecture.md, docs/agent-protocol.md, docs/treasury-controls.md, docs/implementation-status.md, and docs/public-api-and-abuse-controls.md.

## Safety and legal boundaries

No autonomous borrowing, leverage, speculative trading, unlimited transfers, or bypassing KYC/legal restrictions. Receiving funds into an owner-controlled wallet is distinct from offering regulated custody or exchange services. Escrow, custody, exchange and money transmission are not enabled. Obtain qualified local advice before regulated financial activity.
