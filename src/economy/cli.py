import argparse
import json
from pathlib import Path

from .agents import AgentRegistry, RuleBasedAgent
from .controller import EconomyController
from .ledger import AppendOnlyLedger
from .models import LedgerEntry
from .task_store import TaskStore
from .worker import run_once
from .research_sources import GoogleNewsRSSProvider
from .research_store import ResearchCandidateStore
from .research_engine import ResearchDiscoveryEngine
from .economics import UnitEconomics
from .opportunities import Evidence, EvidenceKind, Opportunity
from .opportunity_ranker import rank_readiness
from .hacker_news import HackerNewsSearchProvider
from .research_federation import MultiSourceResearch
from .source_verification import OriginalSourceFetcher
from .source_review import SourceReviewStore, REVIEW_KINDS
from .source_dossier import build_source_dossier
from .shared_brain import SharedBrain
from .collective_learning import CollectiveLearningEngine
from .identity import ParticipantRegistry
from .permissions import CapabilityStore


def demo(data_dir: Path) -> None:
    registry = AgentRegistry()
    registry.register(RuleBasedAgent("opportunity-researcher", "opportunity research"))
    registry.register(RuleBasedAgent("verification-auditor", "verification"))
    controller = EconomyController(registry)
    task = controller.submit("First opportunity scan", "Identify one low-cost digital product idea and define evidence needed to validate demand.", "opportunity-researcher")
    result = controller.execute(task.task_id)
    ledger = AppendOnlyLedger(data_dir / "ledger.jsonl")
    ledger.append(LedgerEntry.create("income", 100, "USD", "Demo-only simulated revenue entry", result.task_id))
    print("DEMO ONLY — no external research, customer, payment, or real revenue was generated.")
    print(f"Task: {result.status.value} | {result.task_id}")
    print(result.result)
    print(f"Simulated ledger balance: ${ledger.balance_minor() / 100:.2f}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Autonomous AI Economy prototype")
    sub = parser.add_subparsers(dest="command", required=True)

    demo_parser = sub.add_parser("demo", help="run a safe local simulation")
    demo_parser.add_argument("--data-dir", type=Path, default=Path("./data"))

    enqueue = sub.add_parser("enqueue", help="persist a task for the local worker")
    enqueue.add_argument("title")
    enqueue.add_argument("objective")
    enqueue.add_argument("agent")
    enqueue.add_argument("--idempotency-key")
    enqueue.add_argument("--max-attempts", type=int, default=3)
    enqueue.add_argument("--data-dir", type=Path, default=Path("./data"))

    worker = sub.add_parser("worker-once", help="claim and execute at most one queued task")
    worker.add_argument("--data-dir", type=Path, default=Path("./data"))

    tasks = sub.add_parser("tasks", help="list persisted tasks")
    tasks.add_argument("--status", choices=["queued", "running", "completed", "failed"])
    tasks.add_argument("--data-dir", type=Path, default=Path("./data"))

    task = sub.add_parser("task", help="show one task and its audit events")
    task.add_argument("task_id")
    task.add_argument("--data-dir", type=Path, default=Path("./data"))

    research = sub.add_parser("research-news", help="discover public news leads (unverified; no sales claims)")
    research.add_argument("query")
    research.add_argument("--limit", type=int, default=10)
    research.add_argument("--data-dir", type=Path, default=Path("./data"))

    research_all = sub.add_parser("research-all", help="search both free public discovery sources; leads remain unverified")
    research_all.add_argument("query")
    research_all.add_argument("--limit", type=int, default=10)
    research_all.add_argument("--data-dir", type=Path, default=Path("./data"))

    research_hn = sub.add_parser("research-hn", help="discover public Hacker News discussions (unverified community leads)")
    research_hn.add_argument("query")
    research_hn.add_argument("--limit", type=int, default=10)
    research_hn.add_argument("--data-dir", type=Path, default=Path("./data"))

    research_fetch = sub.add_parser("research-fetch", help="manually fetch one allowlisted original source; never creates buyer evidence")
    research_fetch.add_argument("url")
    research_fetch.add_argument("--allowed-host", action="append", required=True, help="exact hostname allowed; repeat only for explicitly trusted hosts")

    source_review = sub.add_parser("source-review", help="owner-classify a saved research-fetch JSON snapshot; does not create evidence")
    source_review.add_argument("snapshot_json", type=Path, help="JSON file containing the research-fetch output")
    source_review.add_argument("--kind", required=True, choices=sorted(REVIEW_KINDS))
    source_review.add_argument("--finding", required=True, help="specific finding supported by the page")
    source_review.add_argument("--note", required=True, help="owner review context and limitations")
    source_review.add_argument("--data-dir", type=Path, default=Path("./data"))

    source_review_list = sub.add_parser("source-review-list", help="list owner-classified source snapshots")
    source_review_list.add_argument("--data-dir", type=Path, default=Path("./data"))

    source_dossier = sub.add_parser("source-dossier", help="compile owner-reviewed sources into a conservative opportunity research draft")
    source_dossier.add_argument("--title", required=True)
    source_dossier.add_argument("--buyer-segment", required=True)
    source_dossier.add_argument("--problem", required=True)
    source_dossier.add_argument("--proposed-solution", required=True)
    source_dossier.add_argument("--delivery-format", required=True)
    source_dossier.add_argument("--startup-cost-minor", type=int, required=True)
    source_dossier.add_argument("--currency", default="USD")
    source_dossier.add_argument("--legal-risk-notes", default="")
    source_dossier.add_argument("--output", type=Path, required=True)
    source_dossier.add_argument("--data-dir", type=Path, default=Path("./data"))

    research_list = sub.add_parser("research-list", help="list saved discovery leads")
    research_list.add_argument("--status", choices=["unverified", "owner_reviewed"])
    research_list.add_argument("--data-dir", type=Path, default=Path("./data"))

    research_review = sub.add_parser("research-review", help="record an explicit owner review note")
    research_review.add_argument("candidate_id")
    research_review.add_argument("--note", required=True)
    research_review.add_argument("--data-dir", type=Path, default=Path("./data"))

    research_batch = sub.add_parser("research-batch", help="search several queries and deduplicate public-news leads")
    research_batch.add_argument("--query", action="append", required=True, help="repeat for each query; maximum 10")
    research_batch.add_argument("--limit", type=int, default=10)
    research_batch.add_argument("--data-dir", type=Path, default=Path("./data"))

    economics = sub.add_parser("unit-economics", help="calculate a transparent scenario, not a sales forecast")
    economics.add_argument("--price-minor", type=int, required=True)
    economics.add_argument("--variable-cost-minor", type=int, required=True)
    economics.add_argument("--setup-cost-minor", type=int, default=0)
    economics.add_argument("--platform-fee-bps", type=int, default=0)
    economics.add_argument("--payment-fee-bps", type=int, default=0)
    economics.add_argument("--fixed-fee-minor", type=int, default=0)
    economics.add_argument("--units", type=int, default=1)
    economics.add_argument("--currency", default="USD")

    rank = sub.add_parser("rank-opportunities", help="rank JSON opportunity dossiers by evidence completeness only")
    rank.add_argument("input_json", type=Path)

    prioritize = sub.add_parser("prioritize-opportunities", help="rank operational fit from explicit owner inputs; not a sales forecast")
    prioritize.add_argument("input_json", type=Path, help="JSON list containing dossier and assessment objects")

    brain_add = sub.add_parser("brain-propose", help="propose a shared lesson; owner review required before recall")
    brain_add.add_argument("--title", required=True)
    brain_add.add_argument("--lesson", required=True)
    brain_add.add_argument("--category", required=True)
    brain_add.add_argument("--agent", required=True)
    brain_add.add_argument("--tag", action="append", default=[])
    brain_add.add_argument("--source-ref", action="append", default=[])
    brain_add.add_argument("--confidence", type=float, default=0.5)
    brain_add.add_argument("--data-dir", type=Path, default=Path("./data"))

    brain_review = sub.add_parser("brain-review", help="owner approve or reject a proposed shared lesson")
    brain_review.add_argument("memory_id")
    brain_review.add_argument("--decision", required=True, choices=["approved", "rejected"])
    brain_review.add_argument("--note", required=True)
    brain_review.add_argument("--data-dir", type=Path, default=Path("./data"))

    brain_list = sub.add_parser("brain-list", help="list shared lessons and review status")
    brain_list.add_argument("--status", choices=["proposed", "approved", "rejected"])
    brain_list.add_argument("--data-dir", type=Path, default=Path("./data"))

    brain_recall = sub.add_parser("brain-recall", help="retrieve owner-approved shared lessons")
    brain_recall.add_argument("query")
    brain_recall.add_argument("--limit", type=int, default=8)
    brain_recall.add_argument("--data-dir", type=Path, default=Path("./data"))

    learning_record = sub.add_parser("learning-record", help="record an observed outcome; repeated patterns create unapproved brain proposals")
    learning_record.add_argument("--pattern", required=True, help="stable name for the workflow or experiment being observed")
    learning_record.add_argument("--outcome", required=True, choices=["worked", "failed", "mixed"])
    learning_record.add_argument("--observation", required=True, help="specific observed result, not a prediction")
    learning_record.add_argument("--observed-by", required=True, help="agent or owner who recorded the outcome")
    learning_record.add_argument("--evidence-ref", action="append", required=True, help="source or task record reference; repeat as needed")
    learning_record.add_argument("--data-dir", type=Path, default=Path("./data"))

    learning_summary = sub.add_parser("learning-summary", help="summarize observed outcomes and emitted learning proposals")
    learning_summary.add_argument("--data-dir", type=Path, default=Path("./data"))

    participant_human = sub.add_parser("participant-create-human", help="create a local basic human account record; not KYC")
    participant_human.add_argument("--handle", required=True)
    participant_human.add_argument("--display-name", required=True)
    participant_human.add_argument("--account-control", choices=["unverified", "email", "passkey", "external_credential"], default="unverified")
    participant_human.add_argument("--data-dir", type=Path, default=Path("./data"))

    participant_list = sub.add_parser("participant-list", help="list local active participants")
    participant_list.add_argument("--type", choices=["human", "agent", "organization"])
    participant_list.add_argument("--data-dir", type=Path, default=Path("./data"))

    agent_challenge = sub.add_parser("agent-enrollment-challenge", help="create a one-time challenge for an agent public key")
    agent_challenge.add_argument("--handle", required=True)
    agent_challenge.add_argument("--display-name", required=True)
    agent_challenge.add_argument("--public-key", required=True, help="Ed25519 public key, URL-safe base64")
    agent_challenge.add_argument("--operator-id")
    agent_challenge.add_argument("--data-dir", type=Path, default=Path("./data"))

    agent_complete = sub.add_parser("agent-enrollment-complete", help="verify an agent's Ed25519 challenge signature")
    agent_complete.add_argument("--challenge-id", required=True)
    agent_complete.add_argument("--signature", required=True, help="base64url Ed25519 signature of the exact challenge string")
    agent_complete.add_argument("--data-dir", type=Path, default=Path("./data"))

    capability_grant = sub.add_parser("capability-grant", help="grant one explicitly scoped capability")
    capability_grant.add_argument("--subject", required=True)
    capability_grant.add_argument("--issuer", required=True)
    capability_grant.add_argument("--action", required=True)
    capability_grant.add_argument("--resource", required=True)
    capability_grant.add_argument("--expires-at")
    capability_grant.add_argument("--max-amount-minor", type=int)
    capability_grant.add_argument("--currency")
    capability_grant.add_argument("--data-dir", type=Path, default=Path("./data"))

    authorize = sub.add_parser("authorize", help="evaluate and audit one capability request")
    authorize.add_argument("--subject", required=True)
    authorize.add_argument("--action", required=True)
    authorize.add_argument("--resource", required=True)
    authorize.add_argument("--amount-minor", type=int)
    authorize.add_argument("--currency")
    authorize.add_argument("--approval-ref")
    authorize.add_argument("--data-dir", type=Path, default=Path("./data"))

    args = parser.parse_args()
    if args.command == "demo":
        demo(args.data_dir)
    elif args.command == "enqueue":
        result = TaskStore(args.data_dir / "economy.sqlite3").enqueue(
            args.title, args.objective, args.agent, args.idempotency_key, args.max_attempts
        )
        print(json.dumps(result, indent=2))
    elif args.command == "worker-once":
        result = run_once(TaskStore(args.data_dir / "economy.sqlite3"))
        print(json.dumps(result, indent=2) if result else "Queue empty.")
    elif args.command == "tasks":
        print(json.dumps(TaskStore(args.data_dir / "economy.sqlite3").list_tasks(args.status), indent=2))
    elif args.command == "task":
        store = TaskStore(args.data_dir / "economy.sqlite3")
        print(json.dumps({"task": store.get(args.task_id), "events": store.events(args.task_id)}, indent=2))
    elif args.command == "research-news":
        candidates = GoogleNewsRSSProvider().search(args.query, limit=args.limit)
        saved = ResearchCandidateStore(args.data_dir / "research.sqlite3").save_many(candidates)
        print(json.dumps({
            "query": args.query,
            "candidate_count": len(candidates),
            "persistence": saved,
            "notice": "Discovery leads only. Verify original sources independently; this is not proof of buyer demand or completed sales.",
            "candidates": [item.to_dict() for item in candidates],
        }, indent=2))
    elif args.command == "research-all":
        candidates = MultiSourceResearch().discover(args.query, limit=args.limit)
        saved = ResearchCandidateStore(args.data_dir / "research.sqlite3").save_many(candidates)
        print(json.dumps({
            "query": args.query,
            "candidate_count": len(candidates),
            "providers": ["Google News RSS", "Hacker News Search API (Algolia)"],
            "persistence": saved,
            "notice": "These are two discovery feeds, not verified independent buyer signals. Syndicated or linked material may overlap. Review original sources; engagement and headlines do not prove purchasing intent, sales, or profitability.",
            "candidates": [item.to_dict() for item in candidates],
        }, indent=2))
    elif args.command == "research-hn":
        candidates = HackerNewsSearchProvider().search(args.query, limit=args.limit)
        saved = ResearchCandidateStore(args.data_dir / "research.sqlite3").save_many(candidates)
        print(json.dumps({
            "query": args.query,
            "candidate_count": len(candidates),
            "persistence": saved,
            "notice": "Hacker News community discussions are qualitative leads only. Points/comments are platform engagement, not buyer intent, sales, or willingness to pay. Verify original discussions and independent evidence.",
            "candidates": [item.to_dict() for item in candidates],
        }, indent=2))
    elif args.command == "research-fetch":
        result = OriginalSourceFetcher().fetch(args.url, allowed_hosts=args.allowed_host)
        print(json.dumps({
            "source": result.to_dict(),
            "notice": "Retrieved page content is untrusted research material. A successful fetch does not establish accuracy, buyer intent, independent corroboration, or sales; no evidence record is created.",
        }, indent=2))
    elif args.command == "source-review":
        raw = json.loads(args.snapshot_json.read_text(encoding="utf-8"))
        snapshot = raw.get("source", raw)
        result = SourceReviewStore(args.data_dir / "research.sqlite3").record_review(
            snapshot,
            classification=args.kind,
            finding=args.finding,
            reviewer_note=args.note,
        )
        print(json.dumps(result, indent=2))
    elif args.command == "source-review-list":
        print(json.dumps(SourceReviewStore(args.data_dir / "research.sqlite3").list_reviews(), indent=2))
    elif args.command == "source-dossier":
        dossier = build_source_dossier(
            SourceReviewStore(args.data_dir / "research.sqlite3"),
            title=args.title,
            buyer_segment=args.buyer_segment,
            problem=args.problem,
            proposed_solution=args.proposed_solution,
            delivery_format=args.delivery_format,
            estimated_startup_cost_minor=args.startup_cost_minor,
            currency=args.currency,
            legal_risk_notes=args.legal_risk_notes,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(dossier, indent=2), encoding="utf-8")
        print(json.dumps({
            "output": str(args.output),
            "source_count": len(dossier["source_reviews"]),
            "excluded_source_count": len(dossier["excluded_source_reviews"]),
            "validation": dossier["validation"],
            "notice": dossier["notice"],
        }, indent=2))
    elif args.command == "research-list":
        store = ResearchCandidateStore(args.data_dir / "research.sqlite3")
        print(json.dumps(store.list_candidates(args.status), indent=2))
    elif args.command == "research-review":
        store = ResearchCandidateStore(args.data_dir / "research.sqlite3")
        print(json.dumps(store.mark_owner_reviewed(args.candidate_id, args.note), indent=2))
    elif args.command == "research-batch":
        candidates = ResearchDiscoveryEngine().discover(args.query, limit_per_query=args.limit)
        saved = ResearchCandidateStore(args.data_dir / "research.sqlite3").save_many(candidates)
        print(json.dumps({
            "queries": args.query,
            "candidate_count_after_url_deduplication": len(candidates),
            "persistence": saved,
            "notice": "One discovery provider across multiple queries. Leads remain unverified and are not independent buyer evidence or proof of sales.",
            "candidates": [item.to_dict() for item in candidates],
        }, indent=2))
    elif args.command == "unit-economics":
        model = UnitEconomics(
            price_minor=args.price_minor,
            variable_cost_minor=args.variable_cost_minor,
            fixed_setup_cost_minor=args.setup_cost_minor,
            platform_fee_bps=args.platform_fee_bps,
            payment_fee_bps=args.payment_fee_bps,
            fixed_fee_per_sale_minor=args.fixed_fee_minor,
            currency=args.currency,
        )
        print(json.dumps(model.calculate(args.units), indent=2))
    elif args.command == "learning-record":
        brain = SharedBrain(args.data_dir / "brain.sqlite3")
        engine = CollectiveLearningEngine(args.data_dir / "learning.sqlite3", brain)
        result = engine.record_outcome(
            pattern_key=args.pattern, outcome_label=args.outcome,
            observation=args.observation, observed_by=args.observed_by,
            evidence_refs=args.evidence_ref,
        )
        print(json.dumps(result, indent=2))
    elif args.command == "learning-summary":
        brain = SharedBrain(args.data_dir / "brain.sqlite3")
        engine = CollectiveLearningEngine(args.data_dir / "learning.sqlite3", brain)
        print(json.dumps(engine.summarize(), indent=2))
    elif args.command == "brain-propose":
        brain = SharedBrain(args.data_dir / "brain.sqlite3")
        result = brain.propose(
            title=args.title, lesson=args.lesson, category=args.category,
            created_by=args.agent, tags=args.tag, source_refs=args.source_ref,
            confidence=args.confidence,
        )
        print(json.dumps(result, indent=2))
    elif args.command == "brain-review":
        brain = SharedBrain(args.data_dir / "brain.sqlite3")
        result = brain.review(
            args.memory_id, decision=args.decision, reviewer="owner", note=args.note,
        )
        print(json.dumps(result, indent=2))
    elif args.command == "brain-list":
        print(json.dumps(SharedBrain(args.data_dir / "brain.sqlite3").list_memories(args.status), indent=2))
    elif args.command == "brain-recall":
        print(json.dumps(SharedBrain(args.data_dir / "brain.sqlite3").recall(args.query, limit=args.limit), indent=2))
    elif args.command == "prioritize-opportunities":
        from .opportunity_prioritizer import prioritize_opportunities
        raw = json.loads(args.input_json.read_text(encoding="utf-8"))
        print(json.dumps(prioritize_opportunities(raw), indent=2))
    elif args.command == "rank-opportunities":
        raw = json.loads(args.input_json.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            raise ValueError("input JSON must be a list of opportunity objects")
        opportunities = []
        for item in raw:
            evidence = tuple(Evidence(
                source_name=e["source_name"], url=e["url"], observed_on=e["observed_on"],
                kind=EvidenceKind(e["kind"]), finding=e["finding"],
                independent_source=e.get("independent_source", True),
            ) for e in item.get("evidence", []))
            opportunities.append(Opportunity(
                title=item["title"], buyer_segment=item["buyer_segment"], problem=item["problem"],
                proposed_solution=item["proposed_solution"], delivery_format=item["delivery_format"],
                estimated_startup_cost_minor=item["estimated_startup_cost_minor"],
                currency=item.get("currency", "USD"), legal_risk_notes=item.get("legal_risk_notes", ""),
                evidence=evidence,
            ))
        print(json.dumps([result.to_dict() for result in rank_readiness(opportunities)], indent=2))

    elif args.command == "participant-create-human":
        registry = ParticipantRegistry(args.data_dir / "participants.sqlite3")
        print(json.dumps(registry.create_human(args.handle, args.display_name, args.account_control), indent=2))
    elif args.command == "participant-list":
        print(json.dumps(ParticipantRegistry(args.data_dir / "participants.sqlite3").list_participants(args.type), indent=2))
    elif args.command == "agent-enrollment-challenge":
        registry = ParticipantRegistry(args.data_dir / "participants.sqlite3")
        print(json.dumps(registry.begin_agent_enrollment(args.handle, args.display_name, args.public_key, args.operator_id), indent=2))
    elif args.command == "agent-enrollment-complete":
        registry = ParticipantRegistry(args.data_dir / "participants.sqlite3")
        print(json.dumps(registry.complete_agent_enrollment(args.challenge_id, args.signature), indent=2))
    elif args.command == "capability-grant":
        store = CapabilityStore(args.data_dir / "participants.sqlite3")
        grant_id = store.grant(args.subject, args.issuer, args.action, args.resource,
                               expires_at=args.expires_at, max_amount_minor=args.max_amount_minor,
                               currency=args.currency)
        print(json.dumps({"grant_id": grant_id, "notice": "Local prototype grant; issuer authority is not authenticated by this CLI."}, indent=2))
    elif args.command == "authorize":
        store = CapabilityStore(args.data_dir / "participants.sqlite3")
        print(json.dumps(store.authorize(args.subject, args.action, args.resource,
                                         amount_minor=args.amount_minor, currency=args.currency,
                                         approval_ref=args.approval_ref), indent=2))


if __name__ == "__main__":
    main()
