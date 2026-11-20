"""Idempotent monthly profit close for all shared-treasury agents."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

from .collective_treasury import CollectiveTreasuryStore


class CollectiveProfitPeriodCloser:
    """Close every registered agent's completed period using the fixed 50% owner share.

    The period provider must return a completed accounting period (normally the
    previous UTC calendar month), never the currently active earning period.
    """

    def __init__(self, store: CollectiveTreasuryStore) -> None:
        self.store = store

    @staticmethod
    def previous_utc_month() -> str:
        now = datetime.now(timezone.utc)
        year, month = now.year, now.month - 1
        if month == 0:
            year, month = year - 1, 12
        return f"{year:04d}-{month:02d}"

    async def run_once(self, *, network: str, asset: str, period_id: str) -> dict:
        if not isinstance(period_id, str) or not period_id.strip():
            raise ValueError("period_id must be a non-empty completed accounting period")
        results = []
        blocked = 0
        for agent_id in self.store.list_agents(network, asset):
            try:
                close = self.store.close_period(
                    agent_id, network, asset, period_id,
                    reserve_bps=0, owner_share_bps=5000,
                )
                results.append({
                    "agent_id": agent_id, "period_id": period_id,
                    "status": "closed", "owner_share_minor": close["owner_share_minor"],
                    "net_profit_minor": close["net_profit_minor"],
                })
            except Exception as exc:
                blocked += 1
                results.append({
                    "agent_id": agent_id, "period_id": period_id,
                    "status": "blocked", "reason": str(exc)[:240],
                })
        return {
            "status": "blocked" if blocked else "completed",
            "closed": len(results) - blocked, "blocked": blocked,
            "pending": 0, "uncertain": 0, "failed": blocked,
            "results": results,
        }

    def runtime_callback(self, *, network: str, asset: str = "USDC",
                         period_id_provider: Callable[[], str] | None = None):
        """Return the zero-argument async callback for Accounting runtime."""
        provider = period_id_provider or self.previous_utc_month

        async def callback() -> dict:
            period_id = provider()
            return await self.run_once(
                network=network, asset=asset, period_id=period_id,
            )

        return callback


__all__ = ["CollectiveProfitPeriodCloser"]
