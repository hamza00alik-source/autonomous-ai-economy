# Autonomous AI Economy

A zero-cost-first private AI economy designed to grow into an open ecosystem where independent agents can offer services, earn, and transact.

> Standalone project: not part of OpenCompany or any other business system.

## Current status

**Phase 1 prototype.** Controller, agent registry, task workflow, simulated ledger, tests, and security documentation are being committed. It does not yet operate continuously, call live AI models, serve customers, or move real funds.

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

## Architecture

- **Controller:** routes and executes work.
- **Agent registry:** identifies specialist agents and capabilities.
- **Task protocol:** tracks work and verification.
- **Ledger:** append-only simulated accounting.
- **Treasury boundary:** future real-money adapters remain disabled pending review and approval.

See [architecture](docs/architecture.md), [agent protocol](docs/agent-protocol.md), and [treasury controls](docs/treasury-controls.md).

## Roadmap

1. Private controller, agent registry, task protocol, and auditable ledger.
2. Opportunity research and validation agents.
3. Production, quality assurance, and customer-delivery workflows.
4. First real customer revenue experiment.
5. Hardened payment adapters and owner-approved treasury operations.
6. Optional decentralized agent registration, service contracts, reputation, and settlement.

## Safety

No autonomous borrowing, leverage, speculative trading, unlimited transfers, or bypassing KYC/legal requirements. Receiving funds into an owner-controlled wallet is distinct from offering regulated custody or exchange services. Obtain qualified local advice before regulated financial activity.

## License

Not yet selected. Until a license is added, all rights are reserved.
