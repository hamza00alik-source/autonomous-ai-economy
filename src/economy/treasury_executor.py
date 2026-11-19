"""Safe executor for agent expenses paid by the collective treasury."""
from __future__ import annotations

from contextlib import closing
from typing import Protocol

from .agent_finance import VerifiedTransfer
from .collective_treasury import CollectiveTreasuryStore


class TreasuryTransferVerifier(Protocol):
    async def verify_transfer(self, *, network: str, asset: str, tx_hash: str,
                              source_address: str, destination_address: str,
                              amount_minor: int) -> VerifiedTransfer:
        """Return exact finalized chain evidence or raise while verification is pending."""
        ...


class CollectiveTreasuryPaymentExecutor:
    """Submit a reserved payment once and reconcile it before any retry.

    The reservation is moved to uncertain before calling the provider. This is
    intentionally conservative: if the process dies during submission, no other
    worker can blindly submit the same payment again. Reconciliation must discover
    whether the provider broadcast a transaction and then settle the exact evidence.
    """

    def __init__(self, store: CollectiveTreasuryStore, signer,
                 verifier: TreasuryTransferVerifier) -> None:
        self.store = store
        self.signer = signer
        self.verifier = verifier

    def _reservation(self, reservation_id: str) -> dict | None:
        with closing(self.store._connect()) as db:
            row = db.execute(
                "SELECT * FROM treasury_spend_reservations WHERE reservation_id=?",
                (reservation_id,),
            ).fetchone()
        return dict(row) if row else None

    async def execute(self, reservation_id: str) -> dict:
        reservation = self._reservation(reservation_id)
        if not reservation:
            raise ValueError("spend reservation not found")
        if reservation["status"] != "reserved":
            raise ValueError("only a fresh reserved spend can be submitted")
        wallet = self.store.treasury_wallet(reservation["network"], reservation["asset"])
        if not wallet:
            raise ValueError("collective treasury wallet is not registered")

        # Durable hold before network I/O. A timeout or process crash cannot trigger
        # a duplicate payment; it leaves an explicitly reconcilable uncertain item.
        self.store.mark_uncertain(reservation_id)
        try:
            tx_hash = await self.signer.transfer_usdc(
                destination=reservation["destination"],
                amount_minor=reservation["amount_minor"],
                network=reservation["network"],
            )
        except Exception:
            return {"reservation_id": reservation_id, "status": "uncertain",
                    "reason": "provider outcome must be reconciled before retry"}

        try:
            verified = await self.verifier.verify_transfer(
                network=reservation["network"], asset=reservation["asset"],
                tx_hash=str(tx_hash), source_address=wallet.address,
                destination_address=reservation["destination"],
                amount_minor=reservation["amount_minor"],
            )
            self.store.settle_spend(reservation_id, verified)
        except Exception:
            return {"reservation_id": reservation_id, "status": "uncertain",
                    "tx_hash": str(tx_hash),
                    "reason": "settlement is not yet independently verified"}
        return {"reservation_id": reservation_id, "status": "settled",
                "tx_hash": str(tx_hash)}


__all__ = ["CollectiveTreasuryPaymentExecutor", "TreasuryTransferVerifier"]
