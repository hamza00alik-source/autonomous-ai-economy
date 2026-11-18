"""Long-running, single-host supervisor for isolated built-in and model-backed workers."""
from __future__ import annotations

import argparse
import logging
import signal
import threading
from pathlib import Path
from typing import Callable

from .task_store import TaskStore
from .task_agreements import TaskAgreementStore
from .order_dispatch import dispatch_accepted_orders
from .artifact_export import export_completed_order_artifact
from .worker import run_once
from .ai_task_worker import run_once as run_ai_once

LOG = logging.getLogger("economy.supervisor")


def supervise(
    store: TaskStore,
    *,
    agreements: TaskAgreementStore | None = None,
    poll_seconds: float = 2.0,
    stop_event: threading.Event | None = None,
    max_cycles: int | None = None,
    worker: Callable[[TaskStore], dict | None] = run_once,
    ai_worker: Callable[[TaskStore], dict | None] | None = None,
    financial_scheduler: Callable[[], dict[str, int]] | None = None,
) -> dict[str, int]:
    """Poll until stopped; AI worker is opt-in for tests and enabled by the CLI."""
    if poll_seconds < 0.1 or poll_seconds > 300:
        raise ValueError("poll_seconds must be between 0.1 and 300")
    if max_cycles is not None and max_cycles < 0:
        raise ValueError("max_cycles must be non-negative")
    stop = stop_event or threading.Event()
    cycles = completed = idle = errors = 0
    while not stop.is_set() and (max_cycles is None or cycles < max_cycles):
        cycles += 1
        cycle_had_result = False
        cycle_had_error = False
        if agreements is not None:
            try:
                dispatch_accepted_orders(agreements, store)
            except Exception:
                errors += 1
                cycle_had_error = True
                LOG.exception("Accepted-order dispatch failed; queue remains the recovery source")
        if financial_scheduler is not None:
            try:
                financial_result = financial_scheduler()
                if not isinstance(financial_result, dict) or any(
                    key not in financial_result or isinstance(financial_result[key], bool)
                    or not isinstance(financial_result[key], int) or financial_result[key] < 0
                    for key in ("settled", "blocked")
                ):
                    raise ValueError("financial scheduler must return non-negative settled and blocked counts")
                LOG.info("Simulated financial scheduler: settled=%d blocked=%d", financial_result["settled"], financial_result["blocked"])
                if financial_result["settled"] or financial_result["blocked"]:
                    cycle_had_result = True
            except Exception:
                errors += 1
                cycle_had_error = True
                LOG.exception("Simulated financial scheduler failed; continuing worker lanes")
        callbacks = [worker]
        if ai_worker is not None:
            callbacks.append(ai_worker)
        for callback in callbacks:
            if stop.is_set():
                break
            try:
                result = callback(store)
            except Exception:
                errors += 1
                cycle_had_error = True
                LOG.exception("Worker callback failed; continuing other worker lanes")
                continue
            if result is None:
                continue
            cycle_had_result = True
            if result.get("status") == "completed":
                completed += 1
                if (result.get("assigned_agent") == "order-delivery-agent"
                        and result.get("task_id")):
                    try:
                        artifact_dir = Path(store.path).parent / "deliverables"
                        exported = export_completed_order_artifact(
                            store, result["task_id"], artifact_dir,
                        )
                        LOG.info("Order draft artifact exported: %s", exported["path"])
                    except Exception:
                        errors += 1
                        cycle_had_error = True
                        LOG.exception("Order completed but local artifact export failed")
            else:
                errors += 1
                cycle_had_error = True
        if not cycle_had_result and not cycle_had_error:
            idle += 1
        if stop.is_set() or (max_cycles is not None and cycles >= max_cycles):
            break
        stop.wait(poll_seconds)
    return {"cycles": cycles, "completed": completed, "idle": idle, "errors": errors}



 
def _build_simulated_financial_scheduler(data_dir: Path) -> Callable[[], dict[str, int]]:
    """Build the explicitly opt-in local scheduler; never provisions a policy."""
    from .expense_scheduler import AgentExpenseScheduler
    from .financial_ledger import DoubleEntryLedger
    from .financial_policy import FinancialPolicyStore
    from .financial_spending import AgentSpending
    from .identity import ParticipantRegistry

    registry = ParticipantRegistry(data_dir / "participants.sqlite3")
    policies = FinancialPolicyStore(registry, data_dir / "financial-policies.sqlite3")
    ledger = DoubleEntryLedger(data_dir / "financial-ledger.sqlite3")
    spending = AgentSpending(ledger, policies, data_dir / "financial-spending.sqlite3")
    scheduler = AgentExpenseScheduler(spending, data_dir / "financial-expense-schedules.sqlite3")
    LOG.warning(
        "SIMULATED FINANCIAL SCHEDULER ENABLED: local journal only; "
        "no provider calls, wallet signing, transfers or live payments"
    )
    return scheduler.run_due

def main() -> int:
    parser = argparse.ArgumentParser(description="Run the local autonomous economy worker supervisor")
    parser.add_argument("--data-dir", type=Path, default=Path("./data"))
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    parser.add_argument(
        "--enable-simulated-financial-scheduler", action="store_true",
        help="opt in to local simulated recurring expenses; never makes real payments",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    stop = threading.Event()

    def request_stop(_signum, _frame):
        LOG.info("Shutdown requested; finishing current worker cycle")
        stop.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    args.data_dir.mkdir(parents=True, exist_ok=True)
    store = TaskStore(args.data_dir / "economy.sqlite3")
    agreements = TaskAgreementStore(args.data_dir / "participants.sqlite3")
    LOG.info(
        "Supervisor started; data_dir=%s poll_seconds=%s ai_credentials_configured=%s",
        args.data_dir, args.poll_seconds,
        bool(__import__("os").environ.get("CLOUDFLARE_ACCOUNT_ID")
             and __import__("os").environ.get("CLOUDFLARE_API_TOKEN")),
    )
    financial_scheduler = (
        _build_simulated_financial_scheduler(args.data_dir)
        if args.enable_simulated_financial_scheduler else None
    )
    try:
        stats = supervise(
            store, agreements=agreements, poll_seconds=args.poll_seconds,
            stop_event=stop, ai_worker=run_ai_once,
            financial_scheduler=financial_scheduler,
        )
    except ValueError as exc:
        parser.error(str(exc))
    LOG.info("Supervisor stopped: %s", stats)
    return 0 if stats["errors"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
