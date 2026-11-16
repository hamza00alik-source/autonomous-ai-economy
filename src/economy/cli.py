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

    research_list = sub.add_parser("research-list", help="list saved discovery leads")
    research_list.add_argument("--status", choices=["unverified", "owner_reviewed"])
    research_list.add_argument("--data-dir", type=Path, default=Path("./data"))

    research_review = sub.add_parser("research-review", help="record an explicit owner review note")
    research_review.add_argument("candidate_id")
    research_review.add_argument("--note", required=True)
    research_review.add_argument("--data-dir", type=Path, default=Path("./data"))

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
    elif args.command == "research-list":
        store = ResearchCandidateStore(args.data_dir / "research.sqlite3")
        print(json.dumps(store.list_candidates(args.status), indent=2))
    elif args.command == "research-review":
        store = ResearchCandidateStore(args.data_dir / "research.sqlite3")
        print(json.dumps(store.mark_owner_reviewed(args.candidate_id, args.note), indent=2))


if __name__ == "__main__":
    main()
