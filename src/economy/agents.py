from dataclasses import dataclass
from typing import Protocol

class Agent(Protocol):
    agent_id: str
    role: str
    def execute(self, objective: str) -> str: ...

@dataclass
class RuleBasedAgent:
    agent_id: str
    role: str

    def execute(self, objective: str) -> str:
        clean = " ".join(objective.split())
        if not clean:
            raise ValueError("objective cannot be empty")
        return (f"[{self.role}] Accepted objective for structured analysis: "
                f"{clean[:500]}. This is a deterministic prototype result, not external research.")

class AgentRegistry:
    def __init__(self) -> None:
        self._agents: dict[str, Agent] = {}

    def register(self, agent: Agent) -> None:
        if agent.agent_id in self._agents:
            raise ValueError(f"agent already registered: {agent.agent_id}")
        self._agents[agent.agent_id] = agent

    def get(self, agent_id: str) -> Agent:
        try:
            return self._agents[agent_id]
        except KeyError as exc:
            raise KeyError(f"unknown agent: {agent_id}") from exc

    def list_agents(self) -> list[dict[str, str]]:
        return [{"agent_id": a.agent_id, "role": a.role}
                for a in sorted(self._agents.values(), key=lambda x: x.agent_id)]
