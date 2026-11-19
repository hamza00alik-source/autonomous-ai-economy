"""One-shot worker for routine agent spending from the collective treasury.

The host scheduler may invoke run_once repeatedly. This module does not create
an infinite loop, hold credentials, or make policy decisions on behalf of the owner.
"""
from __future__ import annotations

from contextlib import closing

from .collective_treasury import CollectiveTreasuryStore
from .treasury_executor import CollectiveTreasuryPaymentExecutor


class CollectiveTreasuryWorker:
    """Execute queued reserved spends using the executor's atomic claim boundary."""

    def __init__(self, store: CollectiveTreasuryStore,
                 executor: CollectiveTreasuryPaymentExecutor) -> None:
        self.store = store
        self.executor = executor

    async def run_once(self, *, limit: int = 25) -> dict:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
            raise ValueError("limit must be an integer between 1 and 500")
        with closing(self.store._connect()) as db:
            rows = db.execute(
                """SELECT reservation_id FROM treasury_spend_reservations
                   WHERE status='reserved'
                   ORDER BY created_at, reservation_id LIMIT ?""",
                (limit,),
            ).fetchall()
        results = []
        for row in rows:
            reservation_id = row["reservation_id"]
            try:
                result = await self.executor.execute(reservation_id)
            except ValueError as exc:
                # A different worker may have atomically claimed it after this
                # worker read the queue. Never retry the signer call here.
                result = {
                    "reservation_id": reservation_id,
                    "status": "skipped",
                    "reason": str(exc),
                }
            results.append(result)
        return {
            "examined": len(rows),
            "settled": sum(item["status"] == "settled" for item in results),
            "uncertain": sum(item["status"] == "uncertain" for item in results),
            "gas_cost_pending": sum(
                item.get("gas_cost_status") == "pending" for item in results
            ),
            "skipped": sum(item["status"] == "skipped" for item in results),
            "results": results,
        }


__all__ = ["CollectiveTreasuryWorker"]
