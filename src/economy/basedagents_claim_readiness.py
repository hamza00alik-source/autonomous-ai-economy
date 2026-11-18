"""Fail-closed local readiness checks before considering a BasedAgents claim.

This module performs no network calls, registration, wallet creation, signing,
claiming, delivery, or payment. Callers must supply freshly fetched task data
and independently verified escrow evidence.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from typing import Any
import re


BASE_MAINNET = "eip155:8453"
_ADDRESS = re.compile(r"^0x[0-9a-fA-F]{40}$")


@dataclass(frozen=True)
class ClaimReadiness:
    task_id: str
    state: str
    reasons: tuple[str, ...]
    bounty_usdc: str | None
    claim_allowed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_claim_readiness(task: dict, agent: dict, *,
                             escrow_verified: bool = False) -> ClaimReadiness:
    """Return local readiness only; never authorizes a marketplace write."""
    reasons: list[str] = []
    task_id = task.get("task_id") or task.get("id")
    task_id = task_id.strip()[:160] if isinstance(task_id, str) else ""
    if not task_id:
        reasons.append("missing_task_id")

    if str(task.get("status", "")).lower() != "open":
        reasons.append("task_not_open")
    if task.get("claimable") is not True:
        reasons.append("claimability_not_explicitly_confirmed")

    bounty = task.get("bounty") if isinstance(task.get("bounty"), dict) else {}
    raw_amount = bounty.get("amount_display")
    if raw_amount is None and bounty.get("amount_atomic") is not None:
        try:
            raw_amount = str(Decimal(str(bounty["amount_atomic"])) / Decimal("1000000"))
        except (InvalidOperation, TypeError, ValueError):
            raw_amount = None
    try:
        amount = Decimal(str(raw_amount).replace("USDC", "").replace("$", "").strip())
        if amount < Decimal("0.10"):
            reasons.append("bounty_below_minimum")
    except (InvalidOperation, TypeError, ValueError):
        reasons.append("bounty_missing_or_invalid")

    network = bounty.get("network") or task.get("network")
    if network != BASE_MAINNET:
        reasons.append("unsupported_or_missing_payout_network")

    if escrow_verified is not True:
        reasons.append("escrow_not_independently_verified")

    agent_id = agent.get("agent_id") or agent.get("id")
    if not isinstance(agent_id, str) or not agent_id.startswith("ag_"):
        reasons.append("agent_identity_not_registered")
    if str(agent.get("status", "")).lower() != "active":
        reasons.append("agent_identity_not_active")

    wallet = agent.get("wallet_address")
    if not isinstance(wallet, str) or not _ADDRESS.fullmatch(wallet):
        reasons.append("valid_payout_wallet_missing")
    if agent.get("wallet_network") != network:
        reasons.append("payout_wallet_network_mismatch")

    state = "ready_for_owner_review" if not reasons else "blocked"
    return ClaimReadiness(
        task_id=task_id,
        state=state,
        reasons=tuple(reasons),
        bounty_usdc=str(raw_amount) if raw_amount is not None else None,
        claim_allowed=False,
    )
