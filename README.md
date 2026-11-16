# Autonomous AI Economy

A zero-cost-first private AI economy designed to grow into an open ecosystem where independent agents can offer services, earn, and transact.

> Standalone project: not part of OpenCompany or any other business system.

## Current status

**Early prototype.** Controller, agent registry, task workflow, simulated ledger, evidence-first opportunity validation, tests, and security documentation are committed. It now has two free discovery feeds (Google News RSS and Hacker News), a combined search command, persistent SQLite lead storage, a manual allowlisted original-source retrieval command, owner-classified source snapshots with URL/content-hash deduplication, evidence-readiness ranking, and a unit-economics calculator, and a source-reviewed opportunity dossier generator. Retrieval is not verification: no claim is promoted automatically to buyer evidence. It still does not provide broad web crawling, live AI model execution, real customer acquisition, or revenue. It does not call live AI models, operate continuously, serve customers, or move real funds.

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

The opportunity workflow accepts source-backed findings and checks for independent buyer signals, competitor evidence, costs, legal/policy review, and distinct source URLs. Passing these checks only creates an **owner-review** candidate; it never authorizes publishing or spending. A visible listing is not proof of sales, and the workflow does not infer willingness to pay from weak signals. Free public discovery commands include `economy research-news "your query"` (Google News RSS), `economy research-hn "your query"` (Hacker News discussions), and `economy research-all "your query"` (both providers); all save unverified leads to the same local SQLite review queue. Use `economy research-fetch "https://publisher.example/article" --allowed-host publisher.example` to manually retrieve a single explicitly allowlisted original source; this records a content hash and bounded text sample but does not create evidence. Save its JSON output, then use `economy source-review snapshot.json --kind supports_buyer_problem --finding "..." --note "..."` to record an explicit owner classification; `economy source-review-list` displays reviewed snapshots. Duplicate normalized URLs and identical content hashes are rejected. Owner classification remains unverified research and never creates an evidence object. Use `economy research-list` to inspect them and `economy research-review ID --note "..."` to record an explicit owner review. Review status never creates buyer evidence or validates sales. Additional commands: `economy source-dossier --title ... --buyer-segment ... --problem ... --proposed-solution ... --delivery-format ... --startup-cost-minor 0 --output dossier.json`, `economy research-batch --query "..." --query "..."`, `economy rank-opportunities opportunities.json`, and `economy unit-economics --price-minor 999 --variable-cost-minor 100`. The dossier generator preserves source provenance and marks all compiled evidence candidates non-independent, so it cannot satisfy the independent buyer-evidence gate. Read [live research adapter limits](docs/live-research.md) for formats and limitations.

## Shared Brain and team learning

The team now has a shared SQLite memory store. Agents can propose lessons with source references and confidence notes; only owner-approved lessons are available to every agent through shared recall. Rejected proposals remain auditable. The brain does not self-modify agent code, permissions, prompts, or treasury controls. See [Shared Brain documentation](docs/shared-brain.md).

## Operational opportunity prioritization

Use `economy prioritize-opportunities opportunity_assessments.json` to compare owner-supplied startup/ongoing costs, estimated delivery time, delivery complexity, fulfillment burden, and legal/policy review status. Unknown values remain unknown; cost/time comparisons are limited to matching currencies. The score is a relative operational-fit aid, not a sales, demand, profit, or legal-compliance prediction, and it never authorizes publishing or spending. See [opportunity prioritization](docs/opportunity-prioritization.md).

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
3. Free multi-query public-news RSS discovery plus persistent, deduplicated SQLite lead queue and explicit owner-review notes (implemented; one provider, leads remain unverified).
4. Manual allowlisted source retrieval and owner-classified snapshot review with duplicate URL/content-hash rejection (implemented; not fact verification or evidence creation).
5. Source-reviewed opportunity dossier generator with provenance preservation and non-independent evidence candidates (implemented; still requires independent buyer evidence and owner review).
6. Evidence-readiness ranking and unit-economics scenario calculator (implemented; not demand or sales forecasts). Operational-fit prioritization from explicit owner inputs is also implemented; it is not a commercial forecast.
7. Deterministic specialist workflow for research intake, analysis, product drafting, QA, and listing drafts (implemented; external AI and publishing integrations pending).
8. Persistent SQLite task queue, one-shot worker, idempotent enqueue, bounded retries, task event history, and expired-lease recovery (implemented; hosted scheduling pending).
9. Signed, expiring, single-use owner approval for product drafting (implemented as a local prototype; remote identity and production-grade audit controls pending).
10. First real customer revenue experiment.
11. Hardened payment adapters and owner-approved treasury operations.
12. Optional decentralized agent registration, service contracts, reputation, and settlement.

## Safety

No autonomous borrowing, leverage, speculative trading, unlimited transfers, or bypassing KYC/legal requirements. Receiving funds into an owner-controlled wallet is distinct from offering regulated custody or exchange services. Obtain qualified local advice before regulated financial activity.

## License

Not yet selected. Until a license is added, all rights are reserved.
