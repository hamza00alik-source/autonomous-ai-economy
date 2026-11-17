"""Budget-capped Cloudflare Workers AI adapter.

Inference runs outside the no-network task sandbox. Prompts and credentials are
never persisted; only request hashes, budget reservations and outcomes are stored.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

MODEL_ID = "@cf/zai-org/glm-4.7-flash"
API_ROOT = "https://api.cloudflare.com/client/v4"
ACCOUNT_ID_RE = re.compile(r"^[a-fA-F0-9]{32}$")
MAX_INPUT_CHARS = 8_000
MAX_OUTPUT_TOKENS = 512
DAILY_NEURON_BUDGET = 6_500
INPUT_NEURONS_PER_MILLION = 5_500
OUTPUT_NEURONS_PER_MILLION = 36_400
ESTIMATE_SAFETY_FACTOR = 1.25


class AIConfigurationError(RuntimeError):
    pass


class AIBudgetExceeded(RuntimeError):
    pass


class AIProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class AIResponse:
    text: str
    model: str
    request_id: str
    estimated_neurons: int
    daily_reserved_neurons: int
    daily_budget_neurons: int


class InferenceBudget:
    """Atomic UTC-day inference budget; failed/ambiguous requests are not refunded."""

    def __init__(self, path: str | Path, daily_limit: int = DAILY_NEURON_BUDGET):
        if daily_limit < 1 or daily_limit > DAILY_NEURON_BUDGET:
            raise ValueError(f"daily_limit must be between 1 and {DAILY_NEURON_BUDGET}")
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.daily_limit = daily_limit
        with self._connect() as db:
            db.execute(
                """CREATE TABLE IF NOT EXISTS ai_inference_reservations (
                    request_id TEXT PRIMARY KEY,
                    utc_day TEXT NOT NULL,
                    model TEXT NOT NULL,
                    prompt_sha256 TEXT NOT NULL,
                    estimated_neurons INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    finished_at TEXT
                )"""
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS idx_ai_reservations_day "
                "ON ai_inference_reservations(utc_day)"
            )

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=15, isolation_level=None)
        db.execute("PRAGMA busy_timeout=15000")
        return db

    @staticmethod
    def utc_day() -> str:
        return datetime.now(timezone.utc).date().isoformat()

    def reserve(self, *, model: str, prompt: str, estimated_neurons: int) -> tuple[str, int]:
        if estimated_neurons < 1:
            raise ValueError("estimated_neurons must be positive")
        request_id = uuid.uuid4().hex
        day = self.utc_day()
        now = datetime.now(timezone.utc).isoformat()
        digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT COALESCE(SUM(estimated_neurons), 0) "
                "FROM ai_inference_reservations WHERE utc_day = ?",
                (day,),
            ).fetchone()
            used = int(row[0])
            if used + estimated_neurons > self.daily_limit:
                db.rollback()
                raise AIBudgetExceeded(
                    f"AI daily safety budget would be exceeded: {used}+"
                    f"{estimated_neurons}>{self.daily_limit} neurons. No request sent."
                )
            db.execute(
                """INSERT INTO ai_inference_reservations
                (request_id, utc_day, model, prompt_sha256, estimated_neurons,
                 status, created_at)
                VALUES (?, ?, ?, ?, ?, 'reserved', ?)""",
                (request_id, day, model, digest, estimated_neurons, now),
            )
            db.commit()
        return request_id, used + estimated_neurons

    def finish(self, request_id: str, status: str) -> None:
        if status not in {"succeeded", "failed"}:
            raise ValueError("invalid inference status")
        with self._connect() as db:
            db.execute(
                "UPDATE ai_inference_reservations SET status=?, finished_at=? "
                "WHERE request_id=? AND status='reserved'",
                (status, datetime.now(timezone.utc).isoformat(), request_id),
            )

    def status(self) -> dict:
        day = self.utc_day()
        with self._connect() as db:
            used, calls = db.execute(
                "SELECT COALESCE(SUM(estimated_neurons),0), COUNT(*) "
                "FROM ai_inference_reservations WHERE utc_day=?",
                (day,),
            ).fetchone()
        return {
            "utc_day": day,
            "reserved_neurons": int(used),
            "daily_safety_budget_neurons": self.daily_limit,
            "remaining_neurons": max(0, self.daily_limit - int(used)),
            "requests_reserved": int(calls),
            "note": "Conservative estimates; provider's actual usage dashboard is authoritative.",
        }


def estimate_neurons(messages: list[dict], max_tokens: int) -> int:
    """Conservative preflight estimate for the allowlisted GLM-4.7-Flash model."""
    chars = sum(len(str(item.get("content", ""))) for item in messages)
    if chars > MAX_INPUT_CHARS:
        raise ValueError(f"prompt exceeds {MAX_INPUT_CHARS} characters")
    if not 1 <= max_tokens <= MAX_OUTPUT_TOKENS:
        raise ValueError(f"max_tokens must be between 1 and {MAX_OUTPUT_TOKENS}")
    # Two characters/token is intentionally more conservative than the common
    # four-character heuristic. A 25% reserve covers estimation variance.
    input_tokens = math.ceil(chars / 2)
    raw = (
        input_tokens * INPUT_NEURONS_PER_MILLION
        + max_tokens * OUTPUT_NEURONS_PER_MILLION
    ) / 1_000_000
    return max(1, math.ceil(raw * ESTIMATE_SAFETY_FACTOR))


class CloudflareWorkersAI:
    """Narrow text-generation adapter; no tools, code execution, or outbound actions."""

    def __init__(
        self,
        budget: InferenceBudget,
        *,
        account_id: str | None = None,
        api_token: str | None = None,
        opener: Callable = urllib.request.urlopen,
        timeout: float = 60.0,
    ):
        self.budget = budget
        self.account_id = account_id if account_id is not None else os.getenv("CLOUDFLARE_ACCOUNT_ID", "")
        self.api_token = api_token if api_token is not None else os.getenv("CLOUDFLARE_API_TOKEN", "")
        self.opener = opener
        self.timeout = timeout

    def configured(self) -> bool:
        return bool(ACCOUNT_ID_RE.fullmatch(self.account_id or "") and self.api_token)

    def generate(
        self,
        prompt: str,
        *,
        system: str = "You are a careful specialist agent. Be factual and concise.",
        max_tokens: int = 512,
    ) -> AIResponse:
        if not self.configured():
            raise AIConfigurationError(
                "Set CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN in the runtime environment."
            )
        messages = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
        estimate = estimate_neurons(messages, max_tokens)
        request_id, reserved = self.budget.reserve(
            model=MODEL_ID,
            prompt=system + "\n" + prompt,
            estimated_neurons=estimate,
        )
        url = f"{API_ROOT}/accounts/{self.account_id}/ai/run/{MODEL_ID}"
        payload = json.dumps({
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": 0.2,
        }).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=payload,
            headers={
                "Authorization": f"Bearer {self.api_token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with self.opener(request, timeout=self.timeout) as response:
                raw = response.read(1_000_000)
            document = json.loads(raw.decode("utf-8"))
            if not document.get("success"):
                errors = document.get("errors") or []
                message = str(errors[0].get("message", "provider returned success=false")) if errors else "provider returned success=false"
                raise AIProviderError(message[:300])
            result = document.get("result") or {}
            text = result.get("response")
            if not isinstance(text, str) or not text.strip():
                raise AIProviderError("provider response did not contain text")
            self.budget.finish(request_id, "succeeded")
            return AIResponse(
                text=text,
                model=MODEL_ID,
                request_id=request_id,
                estimated_neurons=estimate,
                daily_reserved_neurons=reserved,
                daily_budget_neurons=self.budget.daily_limit,
            )
        except urllib.error.HTTPError as exc:
            # Do not echo headers, request objects, or credentials into logs/errors.
            self.budget.finish(request_id, "failed")
            detail = ""
            try:
                body = json.loads(exc.read(16_384).decode("utf-8"))
                errors = body.get("errors") or []
                if errors:
                    detail = str(errors[0].get("message", ""))[:200]
            except Exception:
                pass
            raise AIProviderError(f"Cloudflare AI HTTP {exc.code}: {detail or 'request rejected'}") from None
        except AIProviderError:
            self.budget.finish(request_id, "failed")
            raise
        except Exception as exc:
            self.budget.finish(request_id, "failed")
            raise AIProviderError(f"AI request failed ({type(exc).__name__}); reservation retained conservatively.") from None


def runtime_status(data_dir: str | Path) -> dict:
    budget = InferenceBudget(Path(data_dir) / "ai-runtime.sqlite3")
    configured = CloudflareWorkersAI(budget).configured()
    return {
        "provider": "Cloudflare Workers AI",
        "model": MODEL_ID,
        "configured": configured,
        "credentials_present": configured,
        "credentials_values_displayed": False,
        "network_calls_made": False,
        "daily_budget": budget.status(),
        "safety": {
            "model_allowlist_only": True,
            "no_tool_calling": True,
            "no_payment_or_publishing_capabilities": True,
            "no_network_inside_worker_sandbox": True,
            "provider_usage_is_estimated": True,
        },
    }
