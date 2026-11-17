"""One-shot worker. Run repeatedly under an explicitly configured scheduler."""
from __future__ import annotations

from .agents import AgentRegistry, RuleBasedAgent
from .builtin_process import execute_builtin
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
    # The default runtime executes only fixed built-in handlers in a bounded
    # subprocess. An injected registry is retained for tests/local extensions
    # and executes in-process; it is not an isolation boundary.
    if registry is None:
        allowed_ids = ["opportunity-researcher", "verification-auditor"]
    else:
        allowed_ids = [item["agent_id"] for item in registry.list_agents()]
    task = store.claim(allowed_agent_ids=allowed_ids)
    if task is None:
        return None
    lease_token = task.get("lease_token")
    if not lease_token:
        raise RuntimeError("claimed task is missing its lease token")
    try:
        if registry is None:
            result = execute_builtin(task["assigned_agent"], task["objective"])
        else:
            result = registry.get(task["assigned_agent"]).execute(task["objective"])
    except Exception as exc:
        return store.fail(task["task_id"], f"{type(exc).__name__}: {exc}"[:4096], lease_token)
    return store.finish(task["task_id"], result, lease_token)
