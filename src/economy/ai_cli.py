"""Safe status, queue, and explicit invocation CLI for the optional AI provider."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .ai_runtime import CloudflareWorkersAI, InferenceBudget, runtime_status
from .ai_product_agent import AIProductCopyAgent
from .ai_task_worker import queue_product_copy_task
from .task_store import TaskStore


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

    args = parser.parse_args()
    if args.command == "status":
        print(json.dumps(runtime_status(args.data_dir), indent=2))
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
