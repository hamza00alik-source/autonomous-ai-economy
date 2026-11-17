"""Network-capable AI task runner, isolated from the no-network built-in sandbox."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path

from .ai_product_agent import AIProductCopyAgent
from .ai_runtime import CloudflareWorkersAI, InferenceBudget
from .task_store import TaskStore

AI_AGENT_ID = "ai-product-copy-agent"
MAX_FACTS_BYTES = 8_000


def queue_product_copy_task(store: TaskStore, facts: dict) -> dict:
    """Queue one idempotent, single-attempt product-copy task."""
    if not isinstance(facts, dict):
        raise ValueError("product facts must be a JSON object")
    objective = json.dumps(facts, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if len(objective.encode("utf-8")) > MAX_FACTS_BYTES:
        raise ValueError(f"product facts exceed {MAX_FACTS_BYTES} bytes")
    digest = hashlib.sha256(objective.encode("utf-8")).hexdigest()
    return store.enqueue(
        title=f"Draft product listing: {str(facts.get('product_name', 'unnamed product'))[:100]}",
        objective=objective,
        assigned_agent=AI_AGENT_ID,
        idempotency_key=f"ai-product-copy:{digest}",
        max_attempts=1,
    )


def run_once(store: TaskStore, provider: CloudflareWorkersAI | None = None) -> dict | None:
    """Claim at most one AI copy task; no credentials means no claim and no network."""
    if provider is None:
        budget = InferenceBudget(Path(store.path).parent / "ai-runtime.sqlite3")
        provider = CloudflareWorkersAI(budget)
    if not provider.configured():
        return None
    task = store.claim(allowed_agent_ids=[AI_AGENT_ID])
    if task is None:
        return None
    lease_token = task.get("lease_token")
    if not lease_token:
        raise RuntimeError("claimed AI task is missing its lease token")
    try:
        facts = json.loads(task["objective"])
        draft = AIProductCopyAgent(provider).draft(facts)
        result = json.dumps({
            "agent_id": AI_AGENT_ID,
            **asdict(draft),
        }, ensure_ascii=False, sort_keys=True)
    except Exception as exc:
        return store.fail(
            task["task_id"],
            f"{type(exc).__name__}: {str(exc)[:4000]}",
            lease_token,
        )
    return store.finish(task["task_id"], result, lease_token)
