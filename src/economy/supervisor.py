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


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the local autonomous economy worker supervisor")
    parser.add_argument("--data-dir", type=Path, default=Path("./data"))
    parser.add_argument("--poll-seconds", type=float, default=2.0)
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
    try:
        stats = supervise(
            store, agreements=agreements, poll_seconds=args.poll_seconds,
            stop_event=stop, ai_worker=run_ai_once,
        )
    except ValueError as exc:
        parser.error(str(exc))
    LOG.info("Supervisor stopped: %s", stats)
    return 0 if stats["errors"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
