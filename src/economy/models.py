from __future__ import annotations
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any
import uuid

class TaskStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    REJECTED = "rejected"
    FAILED = "failed"

@dataclass(frozen=True)
class Task:
    task_id: str
    title: str
    objective: str
    assigned_agent: str
    status: TaskStatus = TaskStatus.QUEUED
    result: str | None = None
    created_at: str = ""

    @classmethod
    def create(cls, title: str, objective: str, assigned_agent: str) -> "Task":
        return cls(str(uuid.uuid4()), title, objective, assigned_agent,
                   created_at=datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        return data

@dataclass(frozen=True)
class LedgerEntry:
    entry_id: str
    timestamp: str
    entry_type: str
    amount_minor: int
    currency: str
    description: str
    reference: str | None = None
    simulated: bool = True

    @classmethod
    def create(cls, entry_type: str, amount_minor: int, currency: str,
               description: str, reference: str | None = None) -> "LedgerEntry":
        if amount_minor < 0:
            raise ValueError("amount_minor must be non-negative")
        if entry_type not in {"income", "expense", "reserve", "owner_distribution", "reinvestment"}:
            raise ValueError("unsupported ledger entry_type")
        return cls(str(uuid.uuid4()), datetime.now(timezone.utc).isoformat(),
                   entry_type, amount_minor, currency.upper(), description,
                   reference, True)
