"""Safe status and explicit invocation CLI for the optional AI provider."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .ai_runtime import CloudflareWorkersAI, InferenceBudget, runtime_status


def main() -> int:
    parser = argparse.ArgumentParser(description="Budget-capped Cloudflare Workers AI runtime")
    parser.add_argument("--data-dir", type=Path, default=Path("./data"))
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="show credential presence and local budget; makes no network request")
    invoke = sub.add_parser("invoke", help="send one explicitly supplied prompt to the configured AI provider")
    invoke.add_argument("--prompt-file", type=Path, required=True, help="UTF-8 prompt file; prompt is not saved by the runtime")
    invoke.add_argument("--system-file", type=Path, help="optional UTF-8 system prompt file")
    invoke.add_argument("--max-tokens", type=int, default=512)
    args = parser.parse_args()
    if args.command == "status":
        print(json.dumps(runtime_status(args.data_dir), indent=2))
        return 0
    prompt = args.prompt_file.read_text(encoding="utf-8")
    system = args.system_file.read_text(encoding="utf-8") if args.system_file else (
        "You are a careful specialist agent. Be factual, concise, and do not claim actions you did not perform."
    )
    provider = CloudflareWorkersAI(InferenceBudget(args.data_dir / "ai-runtime.sqlite3"))
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
