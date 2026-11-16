from dataclasses import replace
from .agents import AgentRegistry
from .models import Task, TaskStatus

class EconomyController:
    def __init__(self, registry: AgentRegistry) -> None:
        self.registry = registry
        self.tasks: dict[str, Task] = {}

    def submit(self, title: str, objective: str, agent_id: str) -> Task:
        if not title.strip() or not objective.strip():
            raise ValueError("title and objective are required")
        self.registry.get(agent_id)
        task = Task.create(title.strip(), objective.strip(), agent_id)
        self.tasks[task.task_id] = task
        return task

    def execute(self, task_id: str) -> Task:
        task = self.tasks[task_id]
        if task.status is not TaskStatus.QUEUED:
            raise ValueError("only queued tasks can be executed")
        running = replace(task, status=TaskStatus.RUNNING)
        self.tasks[task_id] = running
        try:
            result = self.registry.get(task.assigned_agent).execute(task.objective)
            completed = replace(running, status=TaskStatus.COMPLETED, result=result)
        except Exception as exc:
            completed = replace(running, status=TaskStatus.FAILED, result=f"{type(exc).__name__}: {exc}")
        self.tasks[task_id] = completed
        return completed
