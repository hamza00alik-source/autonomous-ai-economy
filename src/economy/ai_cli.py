"""Safe status, queue, and explicit invocation CLI for the optional AI provider."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .ai_runtime import CloudflareWorkersAI, InferenceBudget, runtime_status
from .ai_product_agent import AIProductCopyAgent
from .ai_task_worker import queue_product_copy_task
from .task_store import TaskStore
from .basedagents_marketplace import BasedAgentsPublicTasks
from .basedagents_opportunities import BasedAgentsOpportunityScanner, PaidOpportunityStore
from .basedagents_task_evaluator import PaidTaskCapabilityEvaluator
from .jobbi_gigs import JobbiPublicGigs, JobbiGigStore


def main() -> int:
    parser = argparse.ArgumentParser(description="Budget-capped Cloudflare Workers AI runtime")
    parser.add_argument("--data-dir", type=Path, default=Path("./data"))
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="show credential presence and local budget; makes no network request")

    invoke = sub.add_parser("invoke", help="send one explicitly supplied prompt to the configured AI provider")
    invoke.add_argument("--prompt-file", type=Path, required=True)
    invoke.add_argument("--system-file", type=Path)
    invoke.add_argument("--max-tokens", type=int, default=512)

    copy = sub.add_parser("draft-copy", help="generate a validated, unpublished product listing draft from facts JSON")
    copy.add_argument("--facts-file", type=Path, required=True)
    copy.add_argument("--output", type=Path, help="new JSON output file; existing files are never overwritten")

    queue = sub.add_parser("queue-copy", help="queue a product-copy task for the always-on AI supervisor")
    queue.add_argument("--facts-file", type=Path, required=True)

    scan = sub.add_parser("scan-paid-tasks", help="discover and rank public BasedAgents tasks; never claims work")
    scan.add_argument("--limit", type=int, default=50)
    scan.add_argument("--minimum-bounty", type=float, default=0.10)
    scan.add_argument("--db", type=Path, help="optional SQLite file; defaults to data-dir/paid-opportunities.sqlite3")

    leads = sub.add_parser("list-paid-tasks", help="list locally stored opportunities awaiting review")
    leads.add_argument("--limit", type=int, default=20)
    leads.add_argument("--db", type=Path, help="optional SQLite file; defaults to data-dir/paid-opportunities.sqlite3")

    evaluate = sub.add_parser("evaluate-paid-tasks", help="fetch task details and check deliverable/acceptance criteria; never claims work")
    evaluate.add_argument("--limit", type=int, default=10)
    evaluate.add_argument("--minimum-bounty", default="0.10")
    evaluate.add_argument("--db", type=Path, help="optional SQLite file; defaults to data-dir/paid-opportunities.sqlite3")

    jobbi_scan = sub.add_parser("scan-jobbi-gigs", help="discover public agent gigs from Jobbi; never claims work")
    jobbi_scan.add_argument("--limit", type=int, default=100)
    jobbi_scan.add_argument("--source", help="optional board key such as algora or agentbounties")
    jobbi_scan.add_argument("--db", type=Path, help="optional SQLite file; defaults to data-dir/jobbi-gigs.sqlite3")

    jobbi_list = sub.add_parser("list-jobbi-gigs", help="list locally stored Jobbi gigs awaiting manual review")
    jobbi_list.add_argument("--limit", type=int, default=20)
    jobbi_list.add_argument("--db", type=Path, help="optional SQLite file; defaults to data-dir/jobbi-gigs.sqlite3")

    evaluated = sub.add_parser("list-task-evaluations", help="list persisted task scope/capability evaluations")
    evaluated.add_argument("--limit", type=int, default=20)
    evaluated.add_argument("--db", type=Path, help="optional SQLite file; defaults to data-dir/paid-opportunities.sqlite3")

    args = parser.parse_args()
    if args.command == "scan-jobbi-gigs":
        db_path = args.db or (args.data_dir / "jobbi-gigs.sqlite3")
        store = JobbiGigStore(db_path)
        gigs = JobbiPublicGigs().search(limit=args.limit, source=args.source)
        print(json.dumps({
            "source": "jobbi",
            "fetched": len(gigs),
            **store.save_many(gigs),
            "notice": "Jobbi is an index, not the payer. All listings remain unverified until checked at their original boards.",
        }, indent=2))
        return 0

    if args.command == "list-jobbi-gigs":
        db_path = args.db or (args.data_dir / "jobbi-gigs.sqlite3")
        store = JobbiGigStore(db_path)
        print(json.dumps(store.list_review_required(limit=args.limit), indent=2))
        return 0

    if args.command == "status":
        print(json.dumps(runtime_status(args.data_dir), indent=2))
        return 0

    if args.command == "scan-paid-tasks":
        db_path = args.db or (args.data_dir / "paid-opportunities.sqlite3")
        store = PaidOpportunityStore(db_path)
        scanner = BasedAgentsOpportunityScanner(
            store, provider=BasedAgentsPublicTasks(),
            minimum_bounty_usdc=args.minimum_bounty,
        )
        print(json.dumps(scanner.scan_once(limit=args.limit), indent=2))
        return 0

    if args.command == "list-paid-tasks":
        db_path = args.db or (args.data_dir / "paid-opportunities.sqlite3")
        store = PaidOpportunityStore(db_path)
        print(json.dumps(store.list_review_required(limit=args.limit), indent=2))
        return 0

    if args.command == "list-task-evaluations":
        db_path = args.db or (args.data_dir / "paid-opportunities.sqlite3")
        store = PaidOpportunityStore(db_path)
        print(json.dumps(store.list_evaluations(limit=args.limit), indent=2))
        return 0

    if args.command == "evaluate-paid-tasks":
        db_path = args.db or (args.data_dir / "paid-opportunities.sqlite3")
        store = PaidOpportunityStore(db_path)
        provider = BasedAgentsPublicTasks()
        evaluator = PaidTaskCapabilityEvaluator(minimum_bounty_usdc=args.minimum_bounty)
        results = []
        for item in store.list_review_required(limit=args.limit):
            lead = item["payload"]
            try:
                detail = provider.get_task(item["external_task_id"])
                result = evaluator.evaluate(lead, detail).to_dict()
            except Exception as exc:
                result = {
                    "task_id": item["external_task_id"],
                    "state": "needs_review",
                    "score": 0,
                    "reasons": [f"detail_fetch_or_evaluation_error:{type(exc).__name__}"],
                    "claim_allowed": False,
                }
            store.save_evaluation(result)
            results.append(result)
        print(json.dumps({
            "evaluated": len(results),
            "qualified_for_local_draft": sum(r["state"] == "qualified_for_local_draft" for r in results),
            "needs_review": sum(r["state"] == "needs_review" for r in results),
            "external_claims": 0,
            "payments": 0,
            "results": results,
        }, indent=2))
        return 0

    if args.command == "queue-copy":
        facts = json.loads(args.facts_file.read_text(encoding="utf-8"))
        store = TaskStore(args.data_dir / "economy.sqlite3")
        task = queue_product_copy_task(store, facts)
        print(json.dumps({
            "task_id": task["task_id"],
            "assigned_agent": task["assigned_agent"],
            "status": task["status"],
            "idempotent": True,
            "max_attempts": task["max_attempts"],
            "notice": "Task is queued. The AI supervisor processes it only when provider credentials are configured.",
        }, indent=2))
        return 0

    provider = CloudflareWorkersAI(InferenceBudget(args.data_dir / "ai-runtime.sqlite3"))
    if args.command == "draft-copy":
        facts = json.loads(args.facts_file.read_text(encoding="utf-8"))
        draft = AIProductCopyAgent(provider).draft(facts)
        payload = json.dumps({
            "agent_id": AIProductCopyAgent.agent_id,
            "title": draft.title,
            "short_description": draft.short_description,
            "description": draft.description,
            "tags": list(draft.tags),
            "ai_disclosure": draft.ai_disclosure,
            "claims_to_verify": list(draft.claims_to_verify),
            "status": draft.status,
            "published": draft.published,
        }, indent=2, ensure_ascii=False) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("x", encoding="utf-8") as handle:
                handle.write(payload)
            print(json.dumps({"saved": str(args.output), "published": False}))
        else:
            print(payload)
        return 0

    prompt = args.prompt_file.read_text(encoding="utf-8")
    system = args.system_file.read_text(encoding="utf-8") if args.system_file else (
        "You are a careful specialist agent. Be factual, concise, and do not claim actions you did not perform."
    )
    response = provider.generate(prompt, system=system, max_tokens=args.max_tokens)
    print(json.dumps({
        "text": response.text,
        "model": response.model,
        "request_id": response.request_id,
        "estimated_neurons": response.estimated_neurons,
        "daily_reserved_neurons": response.daily_reserved_neurons,
        "daily_budget_neurons": response.daily_budget_neurons,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
