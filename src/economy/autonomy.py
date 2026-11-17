"""Bounded autonomous operating policy for routine agent commerce.

This module decides whether an agent may proceed within a preconfigured routine
operating envelope. It does not execute actions, grant platform capabilities,
satisfy legal/provider checks, or authorize transfers/custody.
"""
from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


FORBIDDEN_AUTONOMOUS_ACTIONS = frozenset({
    "spend", "transfer", "financial_execute", "custody", "borrow",
    "leverage", "change_permissions", "issue_owner_grant",
    "publish_unreviewed_financial_product",
})

ROUTINE_ACTIONS = frozenset({
    "discover_demand", "draft_offer", "publish_offer",
    "accept_order", "execute_work", "deliver_work",
    "handle_in_scope_revision", "reconcile_payment",
})


@dataclass(frozen=True)
class AutonomyProfile:
    """Owner-configured operating envelope for one agent.

    daily_order_limit_minor bounds the total value of accepted work per UTC day.
    It is an exposure ceiling, not permission to spend or transfer funds.
    """

    agent_id: str
    allowed_actions: frozenset[str]
    currency: str
    max_order_value_minor: int
    daily_order_limit_minor: int
    enabled: bool = True

    def __post_init__(self) -> None:
        if not self.agent_id.strip():
            raise ValueError("agent_id is required")
        if not self.currency.isalpha() or len(self.currency) != 3:
            raise ValueError("currency must be a three-letter code")
        if self.max_order_value_minor < 0 or self.daily_order_limit_minor < 0:
            raise ValueError("autonomy limits must be non-negative")
        if self.max_order_value_minor > self.daily_order_limit_minor:
            raise ValueError("per-order limit cannot exceed daily order limit")
        if self.allowed_actions & FORBIDDEN_AUTONOMOUS_ACTIONS:
            raise ValueError("profile cannot allow high-risk or forbidden actions")
        if not self.allowed_actions <= ROUTINE_ACTIONS:
            raise ValueError("profile contains an unknown or non-routine action")


class AutonomyGate:
    """Durable, fail-closed gate for routine agent actions and order exposure."""

    def __init__(self, path: str | Path = "./data/economy.sqlite3") -> None:
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS autonomy_order_reservations (
                    reservation_id TEXT PRIMARY KEY,
                    agent_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    amount_minor INTEGER NOT NULL,
                    currency TEXT NOT NULL,
                    utc_day TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(agent_id, idempotency_key)
                )
            """)

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.execute("PRAGMA busy_timeout=10000")
        return db

    def authorize(self, profile: AutonomyProfile, action: str, *,
                  amount_minor: int | None = None, currency: str | None = None,
                  idempotency_key: str | None = None) -> dict[str, str]:
        if not profile.enabled:
            return {"decision": "deny", "reason": "agent autonomy profile is disabled"}
        if action in FORBIDDEN_AUTONOMOUS_ACTIONS or action not in profile.allowed_actions:
            return {"decision": "deny", "reason": "action is outside the routine autonomy allowlist"}
        if action != "accept_order":
            if amount_minor is not None or currency is not None or idempotency_key is not None:
                return {"decision": "deny", "reason": "order budget fields are only valid for accept_order"}
            return {"decision": "allow", "reason": "routine action is within the configured autonomy profile"}
        if (isinstance(amount_minor, bool) or not isinstance(amount_minor, int)
                or amount_minor < 0 or not idempotency_key or not idempotency_key.strip()
                or not currency or currency.upper() != profile.currency.upper()):
            return {"decision": "deny", "reason": "order amount, currency and idempotency key are required"}
        if amount_minor > profile.max_order_value_minor:
            return {"decision": "deny", "reason": "order exceeds the per-order autonomy limit"}

        now = datetime.now(timezone.utc)
        day = now.date().isoformat()
        with self._connect() as db:
            try:
                db.execute("BEGIN IMMEDIATE")
                existing = db.execute(
                    "SELECT amount_minor,currency FROM autonomy_order_reservations "
                    "WHERE agent_id=? AND idempotency_key=?",
                    (profile.agent_id, idempotency_key),
                ).fetchone()
                if existing:
                    if existing == (amount_minor, currency.upper()):
                        db.commit()
                        return {"decision": "allow", "reason": "previous identical order authorization reused"}
                    db.rollback()
                    return {"decision": "deny", "reason": "idempotency key was reused with different order terms"}
                used = db.execute(
                    "SELECT COALESCE(SUM(amount_minor),0) FROM autonomy_order_reservations "
                    "WHERE agent_id=? AND currency=? AND utc_day=?",
                    (profile.agent_id, profile.currency.upper(), day),
                ).fetchone()[0]
                if used + amount_minor > profile.daily_order_limit_minor:
                    db.rollback()
                    return {"decision": "deny", "reason": "daily order exposure limit would be exceeded"}
                db.execute(
                    "INSERT INTO autonomy_order_reservations VALUES(?,?,?,?,?,?,?)",
                    (str(uuid.uuid4()), profile.agent_id, idempotency_key,
                     amount_minor, currency.upper(), day, now.isoformat()),
                )
                db.commit()
                return {"decision": "allow", "reason": "order is within per-order and daily autonomy limits"}
            except sqlite3.Error:
                db.rollback()
                return {"decision": "deny", "reason": "autonomy budget storage unavailable; failing closed"}
