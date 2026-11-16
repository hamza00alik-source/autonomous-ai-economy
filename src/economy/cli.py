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


if __name__ == "__main__":
    main()
