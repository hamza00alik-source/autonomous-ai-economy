"""Deterministic, simulated-only allocation of reconciled receipts."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .financial_ledger import DoubleEntryLedger, FinancialLedgerError


@dataclass(frozen=True)
class AllocationShare:
    account_id: str
    basis_points: int


@dataclass(frozen=True)
class AllocationPolicy:
    policy_id: str
    version: int
    shares: tuple[AllocationShare, ...]

    def __post_init__(self) -> None:
        if not self.policy_id.strip() or self.version < 1:
            raise ValueError("policy_id and positive version are required")
        if not self.shares:
            raise ValueError("at least one allocation share is required")
        if len({share.account_id for share in self.shares}) != len(self.shares):
            raise ValueError("allocation account IDs must be unique")
        if any(not share.account_id.strip() for share in self.shares):
            raise ValueError("allocation account IDs cannot be empty")
        if any(isinstance(share.basis_points, bool)
               or not isinstance(share.basis_points, int)
               or share.basis_points < 0 or share.basis_points > 10_000
               for share in self.shares):
            raise ValueError("basis_points must be an integer from 0 to 10000")
        if sum(share.basis_points for share in self.shares) != 10_000:
            raise ValueError("allocation shares must total exactly 10000 basis points")


def _split_exact(amount_minor: int, shares: Sequence[AllocationShare]) -> list[int]:
    """Largest-remainder apportionment; deterministic and conserves every unit."""
    floors = [(amount_minor * share.basis_points) // 10_000 for share in shares]
    remainder = amount_minor - sum(floors)
    order = sorted(
        range(len(shares)),
        key=lambda i: (-(amount_minor * shares[i].basis_points % 10_000), i),
    )
    for index in order[:remainder]:
        floors[index] += 1
    return floors


def allocate_reconciled_receipt(
    ledger: DoubleEntryLedger,
    *,
    agent_id: str,
    net_amount_minor: int,
    currency: str,
    source_reference: str,
    policy: AllocationPolicy,
    simulated: bool = True,
) -> str:
    """Allocate a reconciled simulated receipt into treasury subaccounts.

    This function is a local accounting prototype. The settlement state and
    policy must be supplied by trusted application code in any future
    integration; this module is not an authentication or signature boundary.
    """
    if simulated is not True:
        raise FinancialLedgerError("live-money allocation is disabled")
    receipt = ledger.simulated_receipt(source_reference)
    if receipt is None or receipt["status"] != "reconciled":
        raise FinancialLedgerError("only ledger-reconciled receipts may be allocated")
    if receipt["agent_id"] != agent_id or receipt["currency"] != currency.upper():
        raise FinancialLedgerError("receipt agent or currency does not match allocation request")
    if receipt["gross_minor"] - receipt["fee_minor"] != net_amount_minor:
        raise FinancialLedgerError("net allocation amount does not match reconciled receipt")
    if not isinstance(agent_id, str) or not agent_id.strip():
        raise FinancialLedgerError("agent_id is required")
    if isinstance(net_amount_minor, bool) or not isinstance(net_amount_minor, int) or net_amount_minor <= 0:
        raise FinancialLedgerError("net_amount_minor must be a positive integer")
    if not isinstance(source_reference, str) or not source_reference.strip():
        raise FinancialLedgerError("source_reference is required")
    currency = currency.upper()
    if len(currency) != 3 or not currency.isascii() or not currency.isalpha():
        raise FinancialLedgerError("currency must be a three-letter code")

    treasury_account = "treasury:available"
    resolved_accounts = [share.account_id.replace("{agent_id}", agent_id) for share in policy.shares]
    if treasury_account in resolved_accounts or len(set(resolved_accounts)) != len(resolved_accounts):
        raise FinancialLedgerError("allocation destinations must be distinct from the source account")

    idempotency_key = f"allocation:{source_reference}:{policy.policy_id}:{policy.version}"
    existing = ledger.find_by_idempotency(idempotency_key)
    if existing is None and ledger.balance_minor(treasury_account, currency) < net_amount_minor:
        raise FinancialLedgerError("insufficient cleared treasury balance")

    amounts = _split_exact(net_amount_minor, policy.shares)
    lines = [{
        "account_id": resolved_accounts[index],
        "direction": "debit",
        "amount_minor": amount,
        "reference": source_reference,
    } for index, amount in enumerate(amounts) if amount > 0]
    lines.append({
        "account_id": treasury_account,
        "direction": "credit",
        "amount_minor": net_amount_minor,
        "reference": source_reference,
    })
    return ledger.post(
        idempotency_key=idempotency_key,
        description=f"Simulated allocation for agent {agent_id}",
        currency=currency,
        lines=lines,
        simulated=True,
    )
