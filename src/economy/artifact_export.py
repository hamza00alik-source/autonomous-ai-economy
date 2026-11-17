"""Export completed built-in order drafts as content-addressed local artifacts."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from .artifact_evidence import create_manifest


def export_completed_order_artifact(task_store, task_id: str,
                                    output_dir: str | Path) -> dict[str, Any]:
    """Write a completed order-agent draft once; never overwrite existing bytes."""
    task = task_store.get(task_id)
    if task is None:
        raise KeyError(task_id)
    if task.get("status") != "completed" or task.get("assigned_agent") != "order-delivery-agent":
        raise ValueError("only completed order-delivery-agent tasks can be exported")
    try:
        order = json.loads(task["objective"])
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("completed task has no valid accepted-order payload") from exc
    if not isinstance(order, dict) or order.get("schema") != "aae.accepted-order/v1":
        raise ValueError("completed task is not an accepted-order task")
    result = task.get("result")
    if not isinstance(result, str) or not result.startswith("# Customer order execution draft"):
        raise ValueError("worker result is not a recognized order execution draft")
    if f"**Task ID:** {order.get('task_id')}\n" not in result:
        raise ValueError("worker result task ID does not match accepted order")
    if "**Status:** DRAFT" not in result or "No payment was collected" not in result:
        raise ValueError("worker result is missing required draft/payment boundaries")

    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("artifact output directory must be a regular directory")
    filename = "order-" + hashlib.sha256(task_id.encode("utf-8")).hexdigest()[:20] + ".md"
    path = directory / filename
    payload = result.encode("utf-8")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags, 0o600)
    except FileExistsError:
        if path.is_symlink() or not path.is_file() or path.read_bytes() != payload:
            raise ValueError("artifact path already exists with different or unsafe content")
    else:
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
        except Exception:
            try:
                path.unlink(missing_ok=True)
            finally:
                raise
    manifest = create_manifest(path, media_type="text/markdown")
    return {
        "task_id": task_id,
        "path": str(path),
        "manifest": manifest,
        "status": "draft_artifact_exported",
        "notice": "This file is an AI-generated execution brief, not completed domain work, buyer delivery, buyer acceptance, or verified revenue.",
    }
