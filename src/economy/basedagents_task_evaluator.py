"""Conservative capability and task-scope evaluation for public paid tasks.

This module only prepares a local execution brief. It never claims work,
signs messages, contacts a buyer, submits deliverables, or handles funds.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
import re
from typing import Any

from .basedagents_opportunities import SUPPORTED_CATEGORIES, SUPPORTED_NETWORKS


@dataclass(frozen=True)
class TaskEvaluation:
    task_id: str
    state: str
    score: int
    reasons: tuple[str, ...]
    deliverable: str | None
    acceptance_criteria: tuple[str, ...]
    bounty_usdc: str | None
    network: str | None
    claim_allowed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _text(value: Any, limit: int = 4000) -> str:
    return value.strip()[:limit] if isinstance(value, str) else ""


def _criteria(value: Any, description: str = "") -> tuple[str, ...]:
    if isinstance(value, list):
        items = [_text(item, 500) for item in value]
    elif isinstance(value, str):
        items = [line.strip(" -*\t")[:500] for line in value.splitlines()]
    else:
        items = []
    if not any(items) and description:
        in_section = False
        for line in description.splitlines():
            stripped = line.strip()
            if stripped.lower() in {"acceptance criteria:", "acceptance evidence:", "success criteria:"}:
                in_section = True
                continue
            if in_section:
                if not stripped:
                    if items:
                        break
                    continue
                if re.match(r"^\s*(?:\d+[.)]|[-*])\s+", line):
                    items.append(stripped[:500])
                elif items:
                    break
    return tuple(item for item in items if item)[:20]


class PaidTaskCapabilityEvaluator:
    """Require explicit deliverables and acceptance criteria before drafting."""

    def __init__(self, *, minimum_bounty_usdc: str = "0.10",
                 maximum_description_chars: int = 12000):
        try:
            self.minimum = Decimal(minimum_bounty_usdc)
        except InvalidOperation as exc:
            raise ValueError("minimum bounty must be a decimal amount") from exc
        if self.minimum < 0:
            raise ValueError("minimum bounty must be non-negative")
        if not 1000 <= maximum_description_chars <= 50000:
            raise ValueError("maximum_description_chars must be between 1000 and 50000")
        self.maximum_description_chars = maximum_description_chars

    def evaluate(self, lead: dict, detail: dict) -> TaskEvaluation:
        task_id = _text(lead.get("task_id"), 160)
        reasons: list[str] = []
        title = _text(detail.get("title") or lead.get("title"), 300)
        description = _text(detail.get("description") or lead.get("description"),
                            self.maximum_description_chars)
        category = _text(detail.get("category") or lead.get("category"), 50).lower()
        status = _text(detail.get("status") or lead.get("status"), 40).lower()
        bounty = detail.get("bounty") if isinstance(detail.get("bounty"), dict) else {}
        amount_text = (bounty.get("amount_display") or lead.get("bounty_usdc"))
        if amount_text is None and bounty.get("amount_atomic") is not None:
            try:
                amount_text = str(Decimal(str(bounty["amount_atomic"])) / Decimal("1000000"))
            except (InvalidOperation, TypeError, ValueError):
                amount_text = None
        network = bounty.get("network") or lead.get("network")
        deliverable = _text(
            detail.get("expected_output") or detail.get("deliverable")
            or detail.get("output_format"), 1000
        )
        criteria = _criteria(
            detail.get("acceptance_criteria") or detail.get("success_criteria"),
            description,
        )
        if not task_id:
            reasons.append("missing_task_id")
        if not title or not description:
            reasons.append("missing_title_or_description")
        if status != "open":
            reasons.append("task_not_open")
        if category not in SUPPORTED_CATEGORIES:
            reasons.append("unsupported_category")
        capabilities = detail.get("required_capabilities") or lead.get("required_capabilities") or []
        if not isinstance(capabilities, list):
            reasons.append("invalid_required_capabilities")
            capabilities = []
        unsupported = {"docker", "x402", "wallet", "external_runtime", "paid_cycle"}
        if any(str(item).lower() in unsupported for item in capabilities):
            reasons.append("requires_unavailable_infrastructure_or_payment_capability")
        combined_scope = (title + " " + description).lower()
        if "genuine external runtime" in combined_scope or "external installation" in combined_scope:
            reasons.append("requires_authorized_external_runtime")
        if ("settled" in combined_scope and "revenue" in combined_scope
                and ("hard spend cap" in combined_scope or "paid cycle" in combined_scope
                     or "at least " in combined_scope)):
            reasons.append("requires_prior_paid_usage_or_revenue_threshold")
        claimable = detail.get("claimable", lead.get("claimable", False))
        if not isinstance(claimable, bool) or not claimable:
            reasons.append("not_claimable")
        if len(description) >= self.maximum_description_chars:
            reasons.append("description_at_safety_limit")
        if not deliverable:
            reasons.append("explicit_deliverable_missing")
        if not criteria:
            reasons.append("explicit_acceptance_criteria_missing")
        try:
            normalized_amount = re.sub(r"(?i)\s*USDC\s*$", "", str(amount_text)).strip().replace("$", "").replace(",", "")
            amount = Decimal(normalized_amount)
        except (InvalidOperation, TypeError, ValueError):
            amount = Decimal("0")
            reasons.append("bounty_missing_or_invalid")
        if amount < self.minimum:
            reasons.append("bounty_below_minimum")
        if network not in SUPPORTED_NETWORKS:
            reasons.append("unsupported_or_missing_network")
        payment_status = detail.get("payment_status")
        if isinstance(payment_status, str) and payment_status.lower() in {"settled", "refunded", "cancelled"}:
            reasons.append("task_payment_or_status_not_actionable")
        score = max(0, 100 - 10 * len(reasons))
        state = "qualified_for_local_draft" if not reasons else "needs_review"
        return TaskEvaluation(
            task_id=task_id, state=state, score=score, reasons=tuple(reasons),
            deliverable=deliverable or None, acceptance_criteria=criteria,
            bounty_usdc=str(amount_text) if amount_text is not None else None,
            network=str(network) if network is not None else None,
            claim_allowed=False,
        )
