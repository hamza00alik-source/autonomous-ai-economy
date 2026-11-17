"""Idempotent dispatch of accepted customer orders into the worker queue.

Dispatch does not claim that work is complete or that payment has occurred.
"""
from __future__ import annotations

import json
from typing import Any


def dispatch_accepted_orders(agreements, task_store, *, limit: int = 100) -> dict[str, Any]:
    """Queue accepted orders exactly once using the task ID as idempotency key."""
    orders = agreements.accepted_orders(limit=limit)
    queued = []
    for order in orders:
        brief = {
            "schema": "aae.accepted-order/v1",
            "task_id": order["task_id"],
            "title": order["title"],
            "scope": order["scope"],
            "acceptance_criteria": order["acceptance_criteria"],
            "due_at": order["due_at"],
            "price_minor": order["price_minor"],
            "currency": order["currency"],
            "buyer_id": order["buyer_id"],
            "provider_id": order["provider_id"],
        }
        task = task_store.enqueue(
            title="Customer order: " + order["title"][:160],
            objective=json.dumps(brief, sort_keys=True, separators=(",", ":")),
            assigned_agent="order-delivery-agent",
            idempotency_key="accepted-order:" + order["task_id"],
            max_attempts=3,
        )
        queued.append({
            "task_id": order["task_id"],
            "queue_task_id": task["task_id"],
            "queue_status": task["status"],
        })
    return {"discovered": len(orders), "queued": queued,
            "notice": "Orders were queued for deterministic draft execution. This is not delivery, buyer acceptance, or payment."}
