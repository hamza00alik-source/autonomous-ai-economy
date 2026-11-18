"""Read-only discovery adapter for the BasedAgents public task marketplace.

This module only reads public tasks. It never registers an agent, claims work,
creates a wallet, signs transactions, or spends funds.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from typing import Callable
from urllib.error import URLError
from urllib.parse import quote, urlencode, urlparse
from urllib.request import Request, urlopen


BASE_URL = "https://api.basedagents.ai"
MAX_RESPONSE_BYTES = 1_000_000


@dataclass(frozen=True)
class PaidTaskLead:
    task_id: str
    title: str
    description: str
    category: str
    bounty_usdc: str | None
    network: str | None
    status: str
    claimable: bool
    source: str = "basedagents"
    verification_status: str = "unverified"
    payment_verified: bool = False
    required_capabilities: tuple[str, ...] = ()

    @property
    def lead_id(self) -> str:
        return sha256(f"{self.source}:{self.task_id}".encode()).hexdigest()[:20]

    def to_dict(self) -> dict:
        result = asdict(self)
        result["lead_id"] = self.lead_id
        return result


class BasedAgentsPublicTasks:
    """Fetch open task leads without credentials or write permissions."""

    def __init__(self, *, timeout_seconds: float = 12,
                 fetcher: Callable[[str, float], bytes] | None = None):
        if not 1 <= timeout_seconds <= 30:
            raise ValueError("timeout_seconds must be between 1 and 30")
        self.timeout_seconds = timeout_seconds
        self._fetcher = fetcher or self._fetch

    @staticmethod
    def _fetch(url: str, timeout: float) -> bytes:
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname != "api.basedagents.ai":
            raise ValueError("only HTTPS api.basedagents.ai is allowed")
        request = Request(url, headers={"Accept": "application/json",
                         "User-Agent": "AutonomousAIEconomy/0.1 public-task-discovery"})
        with urlopen(request, timeout=timeout) as response:
            final = urlparse(response.geturl())
            if final.scheme != "https" or final.hostname != "api.basedagents.ai":
                raise URLError("response host rejected")
            body = response.read(MAX_RESPONSE_BYTES + 1)
        if len(body) > MAX_RESPONSE_BYTES:
            raise ValueError("task response exceeds 1 MB safety limit")
        return body

    def get_task(self, task_id: str) -> dict:
        """Fetch one public task detail record; never authenticates or writes."""
        if not isinstance(task_id, str) or not task_id or len(task_id) > 160:
            raise ValueError("task_id must be a non-empty string up to 160 characters")
        if any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for ch in task_id):
            raise ValueError("task_id contains unsupported characters")
        url = BASE_URL + "/v1/tasks/" + quote(task_id, safe="")
        payload = json.loads(self._fetcher(url, self.timeout_seconds))
        if not isinstance(payload, dict):
            raise ValueError("unexpected task detail response schema")
        task = payload.get("task", payload)
        if not isinstance(task, dict):
            raise ValueError("task detail response is missing task object")
        returned_id = task.get("task_id") or task.get("id")
        if returned_id is not None and returned_id != task_id:
            raise ValueError("task detail ID does not match requested ID")
        return task

    def search(self, *, limit: int = 50, offset: int = 0) -> list[PaidTaskLead]:
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        if offset < 0:
            raise ValueError("offset must be non-negative")
        url = BASE_URL + "/v1/tasks?" + urlencode({
            "status": "open", "limit": limit, "offset": offset,
        })
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname != "api.basedagents.ai":
            raise ValueError("task API host rejected")
        payload = json.loads(self._fetcher(url, self.timeout_seconds))
        rows = payload if isinstance(payload, list) else payload.get("tasks", [])
        if not isinstance(rows, list):
            raise ValueError("unexpected task response schema")
        leads = []
        for row in rows:
            if not isinstance(row, dict) or row.get("status") != "open":
                continue
            task_id = row.get("task_id") or row.get("id")
            title = row.get("title")
            if not isinstance(task_id, str) or not isinstance(title, str):
                continue
            bounty = row.get("bounty")
            amount = None
            network = None
            if isinstance(bounty, dict):
                amount = bounty.get("amount_display")
                if amount is None and bounty.get("amount_atomic") is not None:
                    try:
                        amount = f"{int(bounty['amount_atomic']) / 1_000_000:.2f}"
                    except (TypeError, ValueError):
                        amount = None
                network = bounty.get("network")
            leads.append(PaidTaskLead(
                task_id=task_id,
                title=title[:300],
                description=str(row.get("description") or "")[:4000],
                category=str(row.get("category") or "unknown")[:50],
                bounty_usdc=str(amount) if amount is not None else None,
                network=str(network) if network is not None else None,
                status="open",
                claimable=bool(row.get("claimable", True)),
                required_capabilities=tuple(
                    str(item)[:80] for item in row.get("required_capabilities", [])
                    if isinstance(item, str)
                )[:20] if isinstance(row.get("required_capabilities", []), list) else (),
            ))
        return leads
