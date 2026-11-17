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

The first standalone software product source is products/store-catalog-cleaner/README.md. Build its Gumroad-compatible browser-app ZIP (root-level index.html) with:

```bash
economy-product build --output dist/store-catalog-cleaner.zip
```

This creates a private ZIP with a SHA-256 manifest. It does not upload, publish, or prove demand or revenue. See docs/first-agent-product.md for the product scope, storefront and payout research, and remaining commercial gates.

## First agent-earned revenue

The first commercial milestone is a real payment earned by an AI agent acting as an economic participant—not income earned by the owner operating a freelancer account. Agents must autonomously discover demand, create and publish permitted offers, accept bounded work, execute and deliver it, handle revisions, and reconcile payment. Routine operations should not require owner approval once properly configured. Legally required identity/accountability checks and provider rules must still be met; this project does not bypass KYC or platform restrictions.

The prior Etsy-audit/Upwork freelancer experiment is deprecated. See docs/agent-native-revenue-strategy.md.

## Architecture

The target layers are participant identity/trust, public discovery, agent runtime, task/contract protocol, evidence/reputation, shared intelligence, ledger/accounting, authorization/policy, payment adapters and participant/owner consoles. See docs/always-on-production-launch-gates.md, docs/architecture.md, docs/agent-protocol.md, docs/treasury-controls.md, docs/implementation-status.md, and docs/public-api-and-abuse-controls.md.

## Safety and legal boundaries

No autonomous borrowing, leverage, speculative trading, unlimited transfers, or bypassing KYC/legal restrictions. Receiving funds into an owner-controlled wallet is distinct from offering regulated custody or exchange services. Escrow, custody, exchange and money transmission are not enabled. Obtain qualified local advice before regulated financial activity.
