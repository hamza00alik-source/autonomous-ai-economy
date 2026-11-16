"""One-shot worker. Run repeatedly under an explicitly configured scheduler."""
from __future__ import annotations

from .agents import AgentRegistry, RuleBasedAgent
from .task_store import TaskStore


def build_registry() -> AgentRegistry:
    registry = AgentRegistry()
    registry.register(RuleBasedAgent("opportunity-researcher", "opportunity research"))
    registry.register(RuleBasedAgent("verification-auditor", "verification"))
    return registry


def run_once(store: TaskStore) -> dict | None:
    task = store.claim()
    if task is None:
        return None
    try:
        result = build_registry().get(task["assigned_agent"]).execute(task["objective"])
        return store.finish(task["task_id"], result)
    except Exception as exc:
        return store.fail(task["task_id"], f"{type(exc).__name__}: {exc}")
