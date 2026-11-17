"""Long-running, single-host supervisor for the built-in economy worker."""
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

LOG = logging.getLogger("economy.supervisor")


def supervise(store: TaskStore, *, agreements: TaskAgreementStore | None = None,
              poll_seconds: float = 2.0,
              stop_event: threading.Event | None = None,
              max_cycles: int | None = None,
              worker: Callable[[TaskStore], dict | None] = run_once) -> dict[str, int]:
    """Poll until stopped; max_cycles supports deterministic tests."""
    if poll_seconds < 0.1 or poll_seconds > 300:
        raise ValueError("poll_seconds must be between 0.1 and 300")
    if max_cycles is not None and max_cycles < 0:
        raise ValueError("max_cycles must be non-negative")
    stop = stop_event or threading.Event()
    cycles = completed = idle = errors = 0
    while not stop.is_set() and (max_cycles is None or cycles < max_cycles):
        cycles += 1
        try:
            if agreements is not None:
                dispatch_accepted_orders(agreements, store)
            result = worker(store)
            if (result is not None and result.get("status") == "completed"
                    and result.get("assigned_agent") == "order-delivery-agent"
                    and result.get("task_id")):
                artifact_dir = Path(store.path).parent / "deliverables"
                exported = export_completed_order_artifact(
                    store, result["task_id"], artifact_dir,
                )
                LOG.info("Order draft artifact exported: %s", exported["path"])
            if result is None:
                idle += 1
            elif result.get("status") == "completed":
                completed += 1
            else:
                errors += 1
        except Exception:
            errors += 1
            LOG.exception("Worker cycle failed; queue remains the recovery source")
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
    LOG.info("Supervisor started; data_dir=%s poll_seconds=%s", args.data_dir, args.poll_seconds)
    try:
        stats = supervise(store, agreements=agreements, poll_seconds=args.poll_seconds, stop_event=stop)
    except ValueError as exc:
        parser.error(str(exc))
    LOG.info("Supervisor stopped: %s", stats)
    return 0 if stats["errors"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
