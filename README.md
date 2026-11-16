# Autonomous AI Economy

A zero-cost-first private AI economy designed to grow into an open ecosystem where independent agents can offer services, earn, and transact.

> Standalone project: not part of OpenCompany or any other business system.

## Current status

**Early prototype.** Controller, agent registry, task workflow, simulated ledger, evidence-first opportunity validation, tests, and security documentation are committed. It now has a narrow public-news RSS discovery command, but not general web research or source verification. It does not call live AI models, operate continuously, serve customers, or move real funds.

## Principles

- Start with free and open-source resources; no paid services without owner approval.
- Prove a real customer and positive net revenue before scaling.
- Agents are workers, not owners. The human owner retains legal ownership and treasury authority.
- Default to dry-run for financial actions.
- Never commit API keys, passwords, seed phrases, or private keys.
- Require explicit owner approval for publishing, contracts, spending, custody, or irreversible transfers.

## Quick start

Requires Python 3.11+.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
economy demo
```

Windows PowerShell activation: `.venv\Scripts\Activate.ps1`.

The demo uses simulated records only. It does not connect to a wallet or payment provider.

## Specialist agents

The deterministic specialist workflow is implemented in `src/economy/specialist_agents.py`. It organizes supplied evidence, evaluates opportunities, requires a signed, expiring, single-use owner approval token before product drafting, runs structural QA, and prepares an unpublished listing draft only after QA passes. These agents do not browse, contact buyers, publish, or spend. See [specialist workflow](docs/specialist-workflow.md) and [owner approval controls](docs/owner-approval.md).

## Persistent queue and worker

The SQLite task queue survives process restarts and exposes `economy enqueue`, `economy worker-once`, `economy tasks`, and `economy task <id>`. It records task events, supports idempotency keys, and bounds retries. The worker executes at most one deterministic local task per invocation. It is not an always-on hosted service; see [durable queue](docs/durable-queue.md) for important crash-recovery and deployment limits.

## Opportunity validation

The opportunity workflow accepts source-backed findings and checks for independent buyer signals, competitor evidence, costs, legal/policy review, and distinct source URLs. Passing these checks only creates an **owner-review** candidate; it never authorizes publishing or spending. A visible listing is not proof of sales, and the workflow does not infer willingness to pay from weak signals. A first live, free public-news RSS discovery command is available as `economy research-news "your query"`; it returns unverified leads only and does not feed them into validation automatically. See [research validation](docs/research-validation.md) and [live research adapter limits](docs/live-research.md).

## Architecture

- **Controller:** routes and executes work.
- **Agent registry:** identifies specialist agents and capabilities.
- **Specialist workflow:** research intake, opportunity analysis, approval-gated product drafting, QA, and listing-draft preparation.
- **Task protocol:** tracks work and verification.
- **Ledger:** append-only simulated accounting.
- **Treasury boundary:** future real-money adapters remain disabled pending review and approval.

See [architecture](docs/architecture.md), [agent protocol](docs/agent-protocol.md), and [treasury controls](docs/treasury-controls.md).

## Roadmap

1. Private controller, agent registry, task protocol, and auditable ledger.
2. Evidence-first opportunity intake and validation (implemented).
3. Free public-news RSS discovery command (implemented; leads remain unverified and require source review).
4. Deterministic specialist workflow for research intake, analysis, product drafting, QA, and listing drafts (implemented; external AI and publishing integrations pending).
5. Persistent SQLite task queue, one-shot worker, idempotent enqueue, bounded retries, task event history, and expired-lease recovery (implemented; hosted scheduling pending).
6. Signed, expiring, single-use owner approval for product drafting (implemented as a local prototype; remote identity and production-grade audit controls pending).
7. First real customer revenue experiment.
8. Hardened payment adapters and owner-approved treasury operations.
9. Optional decentralized agent registration, service contracts, reputation, and settlement.

## Safety

No autonomous borrowing, leverage, speculative trading, unlimited transfers, or bypassing KYC/legal requirements. Receiving funds into an owner-controlled wallet is distinct from offering regulated custody or exchange services. Obtain qualified local advice before regulated financial activity.

## License

Not yet selected. Until a license is added, all rights are reserved.
