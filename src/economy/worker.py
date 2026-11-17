"""One-shot worker. Run repeatedly under an explicitly configured scheduler."""
from __future__ import annotations

from .agents import AgentRegistry, RuleBasedAgent
from .task_store import TaskStore


def build_registry() -> AgentRegistry:
    registry = AgentRegistry()
    registry.register(RuleBasedAgent("opportunity-researcher", "opportunity research"))
    registry.register(RuleBasedAgent("verification-auditor", "verification"))
    return registry


def run_once(store: TaskStore, registry: AgentRegistry | None = None) -> dict | None:
    """Execute at most one task addressed to an explicitly registered runtime agent.

    Unknown or unavailable agents are never claimed, so their work remains queued.
    This is a deterministic local worker, not an OS/process sandbox.
    """
    active_registry = registry if registry is not None else build_registry()
    registered_ids = [item["agent_id"] for item in active_registry.list_agents()]
    task = store.claim(allowed_agent_ids=registered_ids)
    if task is None:
        return None
    lease_token = task.get("lease_token")
    if not lease_token:
        raise RuntimeError("claimed task is missing its lease token")
    try:
        result = active_registry.get(task["assigned_agent"]).execute(task["objective"])
    except Exception as exc:
        return store.fail(task["task_id"], f"{type(exc).__name__}: {exc}"[:4096], lease_token)
    return store.finish(task["task_id"], result, lease_token)
