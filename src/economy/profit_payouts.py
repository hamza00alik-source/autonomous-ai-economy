"""Automatic master profit distribution orchestration.

The worker requires a policy-enforcing external signer and an independent chain
verifier. It never accepts an LLM-supplied 'verified' boolean or handles keys.
"""
from __future__ import annotations

from typing import Protocol

from .agent_finance import AgentFinanceStore, VerifiedTransfer


class TreasurySigner(Protocol):
    def transfer(self, *, agent_id: str, network: str, asset: str,
                 source_address: str, destination_address: str,
                 amount_minor: int, idempotency_key: str) -> str:
        """Broadcast exact transfer under an independently enforced signer policy."""
        ...


class ChainTransferVerifier(Protocol):
    def verify_transfer(self, *, network: str, asset: str, tx_hash: str,
                        source_address: str, destination_address: str,
                        amount_minor: int) -> VerifiedTransfer:
        """Return a transfer only after checking finality and exact on-chain fields."""
        ...


class ProfitPayoutWorker:
    """Pays all pending owner shares without a per-payment human approval."""

    def __init__(self, store: AgentFinanceStore, signer: TreasurySigner,
                 verifier: ChainTransferVerifier) -> None:
        self.store = store
        self.signer = signer
        self.verifier = verifier

    def process_pending(self, *, limit: int = 50) -> list[dict[str, str]]:
        results: list[dict[str, str]] = []
        for period in self.store.list_pending_distributions(limit=limit):
            agent_id = period["agent_id"]
            network = period["network"]
            asset = period["asset"]
            agent = self.store.wallet(agent_id, "agent", network, asset)
            master = self.store.wallet(period["master_id"], "master", network, asset)
            if not agent or not master:
                results.append({"period_key": period["period_key"], "status": "blocked",
                                "reason": "agent or master wallet is not registered"})
                continue
            amount = int(period["master_due_minor"])
            # Stable idempotency key lets the signer safely resume after worker restarts.
            idempotency_key = "master-profit:" + period["period_key"]
            try:
                tx_hash = self.signer.transfer(
                    agent_id=agent_id, network=network, asset=asset,
                    source_address=agent.address, destination_address=master.address,
                    amount_minor=amount, idempotency_key=idempotency_key,
                )
                if not isinstance(tx_hash, str) or not tx_hash.strip():
                    raise ValueError("signer did not return a transaction hash")
                verified = self.verifier.verify_transfer(
                    network=network, asset=asset, tx_hash=tx_hash,
                    source_address=agent.address, destination_address=master.address,
                    amount_minor=amount,
                )
                if not isinstance(verified, VerifiedTransfer):
                    raise ValueError("chain verifier returned an invalid transfer object")
                self.store.mark_owner_distribution_paid(
                    agent_id, network, asset, period["period_id"], transfer=verified,
                )
                results.append({"period_key": period["period_key"], "status": "paid",
                                "tx_hash": tx_hash})
            except Exception as exc:
                # Keep obligation pending; the next scheduled pass can safely retry.
                results.append({"period_key": period["period_key"], "status": "pending",
                                "reason": str(exc)[:240]})
        return results
