"""Persist and rank external paid-task leads without claiming or spending.

The scanner is deliberately discovery-only. A separate reviewed executor must
validate task terms and capability fit before any external claim or delivery.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .basedagents_marketplace import BasedAgentsPublicTasks, PaidTaskLead


SUPPORTED_CATEGORIES = frozenset({"research", "content", "code", "data", "automation"})
SUPPORTED_NETWORKS = frozenset({"eip155:8453", "eip155:84532"})


class PaidOpportunityStore:
    def __init__(self, path: str | Path = "./data/paid-opportunities.sqlite3"):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS paid_opportunity_leads (
                    lead_id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    external_task_id TEXT NOT NULL,
                    category TEXT NOT NULL,
                    bounty_usdc TEXT,
                    network TEXT,
                    claimable INTEGER NOT NULL,
                    fit_score INTEGER NOT NULL,
                    state TEXT NOT NULL CHECK(state IN ('discovered','review_required','rejected')),
                    payload_json TEXT NOT NULL,
                    discovered_at TEXT NOT NULL,
                    UNIQUE(source, external_task_id)
                )
            """)

    def save(self, lead: PaidTaskLead, *, minimum_bounty_usdc: float = 0.10) -> dict:
        if minimum_bounty_usdc < 0:
            raise ValueError("minimum bounty must be non-negative")
        try:
            amount = float(lead.bounty_usdc) if lead.bounty_usdc is not None else 0.0
        except (TypeError, ValueError):
            amount = 0.0
        category_ok = lead.category in SUPPORTED_CATEGORIES
        network_ok = lead.network in SUPPORTED_NETWORKS
        paid_ok = amount >= minimum_bounty_usdc and lead.bounty_usdc is not None
        claimable = bool(lead.claimable)
        score = (40 if category_ok else 0) + (30 if network_ok else 0) + (20 if paid_ok else 0) + (10 if claimable else 0)
        state = "review_required" if score == 100 else "rejected"
        payload = json.dumps(lead.to_dict(), sort_keys=True, separators=(",", ":"))
        now = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self.path) as db:
            db.execute("""
                INSERT INTO paid_opportunity_leads
                (lead_id,source,external_task_id,category,bounty_usdc,network,
                 claimable,fit_score,state,payload_json,discovered_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(source,external_task_id) DO UPDATE SET
                  category=excluded.category,bounty_usdc=excluded.bounty_usdc,
                  network=excluded.network,claimable=excluded.claimable,
                  fit_score=excluded.fit_score,state=excluded.state,
                  payload_json=excluded.payload_json
            """, (lead.lead_id, lead.source, lead.task_id, lead.category,
                  lead.bounty_usdc, lead.network, int(claimable), score, state, payload, now))
            row = db.execute(
                "SELECT lead_id,fit_score,state FROM paid_opportunity_leads WHERE source=? AND external_task_id=?",
                (lead.source, lead.task_id),
            ).fetchone()
        return {"lead_id": row[0], "fit_score": row[1], "state": row[2]}

    def list_review_required(self, limit: int = 50) -> list[dict]:
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        with sqlite3.connect(self.path) as db:
            db.row_factory = sqlite3.Row
            rows = db.execute("""
                SELECT lead_id,external_task_id,category,bounty_usdc,network,
                       fit_score,payload_json,discovered_at
                FROM paid_opportunity_leads WHERE state='review_required'
                ORDER BY fit_score DESC, discovered_at ASC LIMIT ?
            """, (limit,)).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["payload"] = json.loads(item.pop("payload_json"))
            result.append(item)
        return result


class BasedAgentsOpportunityScanner:
    """One bounded public scan; never accepts tasks or invokes payment endpoints."""

    def __init__(self, store: PaidOpportunityStore,
                 provider: BasedAgentsPublicTasks | None = None,
                 minimum_bounty_usdc: float = 0.10):
        self.store = store
        self.provider = provider or BasedAgentsPublicTasks()
        self.minimum_bounty_usdc = minimum_bounty_usdc

    def scan_once(self, *, limit: int = 50) -> dict:
        leads = self.provider.search(limit=limit)
        saved = [self.store.save(lead, minimum_bounty_usdc=self.minimum_bounty_usdc)
                 for lead in leads]
        return {
            "source": "basedagents",
            "fetched": len(leads),
            "review_required": sum(item["state"] == "review_required" for item in saved),
            "rejected": sum(item["state"] == "rejected" for item in saved),
            "actions_taken": ["public_read_only_discovery", "local_deduplicated_storage"],
            "external_claims": 0,
            "payments": 0,
        }
