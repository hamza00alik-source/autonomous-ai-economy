"""Private Cloudflare Worker client for budgeted, scheduled product-copy jobs."""
from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable, Mapping


class CloudflareWorkerError(RuntimeError):
    pass


def _base_url(value: str) -> str:
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise ValueError("AAE_WORKER_URL must be an HTTPS origin without embedded credentials")
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise ValueError("AAE_WORKER_URL must be the worker origin only")
    return f"https://{parsed.netloc}"


def _read_json_response(response) -> dict:
    try:
        data = json.loads(response.read(1_000_000).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CloudflareWorkerError("private worker returned invalid JSON") from exc
    if not isinstance(data, dict):
        raise CloudflareWorkerError("private worker returned an invalid response object")
    return data


def _request(url: str, token: str, *, method: str, body: bytes | None,
             opener: Callable, timeout: float) -> dict:
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }
    if body is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with opener(request, timeout=timeout) as response:
            data = _read_json_response(response)
    except urllib.error.HTTPError as exc:
        raise CloudflareWorkerError(f"private worker returned HTTP {exc.code}") from None
    except CloudflareWorkerError:
        raise
    except Exception as exc:
        raise CloudflareWorkerError(f"private worker request failed ({type(exc).__name__})") from None
    if "error" in data and not data.get("task_id"):
        raise CloudflareWorkerError(str(data["error"])[:300])
    return data


def submit_and_wait(
    *,
    facts_path: str | Path,
    output_path: str | Path,
    worker_url: str,
    token: str,
    timeout_seconds: int = 900,
    poll_interval: int = 15,
    opener: Callable = urllib.request.urlopen,
    sleep: Callable = time.sleep,
    monotonic: Callable = time.monotonic,
) -> dict:
    if not token:
        raise ValueError("AAE_QUEUE_TOKEN is required")
    if not 30 <= timeout_seconds <= 1800:
        raise ValueError("timeout_seconds must be between 30 and 1800")
    if not 5 <= poll_interval <= 60:
        raise ValueError("poll_interval must be between 5 and 60 seconds")
    base = _base_url(worker_url)
    facts = json.loads(Path(facts_path).read_text(encoding="utf-8"))
    if not isinstance(facts, dict):
        raise ValueError("product facts must be a JSON object")
    body = json.dumps(facts, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(body) > 8_000:
        raise ValueError("product facts exceed the private worker's 8 KB limit")
    queued = _request(
        base + "/v1/tasks/product-copy", token,
        method="POST", body=body, opener=opener, timeout=15,
    )
    task_id = queued.get("task_id")
    if not isinstance(task_id, str) or not task_id:
        raise CloudflareWorkerError("private worker did not return a task ID")
    deadline = monotonic() + timeout_seconds
    while True:
        status = _request(
            base + "/v1/tasks/product-copy/" + urllib.parse.quote(task_id, safe=""),
            token, method="GET", body=None, opener=opener, timeout=15,
        )
        state = status.get("status")
        if state == "completed":
            result = status.get("result")
            required = ("title", "short_description", "description", "tags", "ai_disclosure")
            if not isinstance(result, dict) or any(key not in result for key in required):
                raise CloudflareWorkerError("completed task did not contain a valid product-copy draft")
            if result.get("published") is not False or result.get("status") != "draft":
                raise CloudflareWorkerError("private worker result is not an unpublished draft")
            output = Path(output_path)
            output.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(result, handle, indent=2, ensure_ascii=False)
                handle.write("\n")
            return {"task_id": task_id, "status": "completed", "published": False, "output": str(output)}
        if state in {"failed", "blocked_budget", "stalled"}:
            raise CloudflareWorkerError(f"product-copy task ended with status {state}: {str(status.get('error') or '')[:300]}")
        if state not in {"queued", "running"}:
            raise CloudflareWorkerError(f"private worker returned unexpected task status: {state}")
        if monotonic() >= deadline:
            raise CloudflareWorkerError(f"timed out waiting for task {task_id}; check its status before retrying")
        sleep(poll_interval)


def main() -> int:
    parser = argparse.ArgumentParser(description="Queue product facts on the private Cloudflare worker and wait for the draft")
    parser.add_argument("--facts-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=int, default=900)
    parser.add_argument("--poll-interval", type=int, default=15)
    args = parser.parse_args()
    worker_url = os.getenv("AAE_WORKER_URL", "")
    token = os.getenv("AAE_QUEUE_TOKEN", "")
    result = submit_and_wait(
        facts_path=args.facts_file,
        output_path=args.output,
        worker_url=worker_url,
        token=token,
        timeout_seconds=args.timeout_seconds,
        poll_interval=args.poll_interval,
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
