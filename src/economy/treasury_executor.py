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


class TreasuryGasFeeVerifier(Protocol):
    def transaction_fee_wei(self, tx_hash: str) -> dict:
        """Return a finalized canonical receipt fee breakdown in wei."""
        ...


class NativeGasPriceOracle(Protocol):
    async def quote_native_fee_usdc(self, *, network: str, fee_wei: int) -> dict:
        """Return usdc_cost_minor, price_source and price_observed_at."""
        ...


class CollectiveTreasuryPaymentExecutor:
    """Submit a reserved payment once and reconcile it before any retry.

    The reservation is moved to uncertain before calling the provider. This is
    intentionally conservative: if the process dies during submission, no other
    worker can blindly submit the same payment again. Reconciliation must discover
    whether the provider broadcast a transaction and then settle the exact evidence.
    """

    def __init__(self, store: CollectiveTreasuryStore, signer,
                 verifier: TreasuryTransferVerifier, *,
                 gas_fee_verifier: TreasuryGasFeeVerifier | None = None,
                 gas_price_oracle: NativeGasPriceOracle | None = None) -> None:
        self.store = store
        self.signer = signer
        self.verifier = verifier
        self.gas_fee_verifier = gas_fee_verifier
        self.gas_price_oracle = gas_price_oracle

    def _gas_cost_recorded(self, reservation_id: str) -> bool:
        with closing(self.store._connect()) as db:
            row = db.execute(
                "SELECT 1 FROM treasury_gas_costs WHERE reservation_id=?",
                (reservation_id,),
            ).fetchone()
        return row is not None

    async def _record_gas_cost(self, reservation: dict, tx_hash: str) -> bool:
        if self._gas_cost_recorded(reservation["reservation_id"]):
            return True
        if not self.gas_fee_verifier or not self.gas_price_oracle:
            return False
        fee = self.gas_fee_verifier.transaction_fee_wei(tx_hash)
        if not isinstance(fee, dict) or not isinstance(fee.get("total_fee_wei"), int):
            raise ValueError("gas fee verifier returned malformed fee evidence")
        quote = await self.gas_price_oracle.quote_native_fee_usdc(
            network=reservation["network"], fee_wei=fee["total_fee_wei"]
        )
        if not isinstance(quote, dict):
            raise ValueError("gas price oracle returned malformed valuation")
        self.store.record_gas_cost(
            reservation_id=reservation["reservation_id"],
            network=reservation["network"], tx_hash=tx_hash,
            gas_fee_wei=fee["total_fee_wei"],
            usdc_cost_minor=quote["usdc_cost_minor"],
            price_source=quote["price_source"],
            price_observed_at=quote["price_observed_at"],
        )
        return True

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

        # Atomic compare-and-set claim before network I/O. A second worker that
        # read the same reserved row cannot also submit the payment.
        if not self.store.claim_spend_submission(reservation_id):
            raise ValueError("spend reservation was already claimed by another worker")
        try:
            tx_hash = await self.signer.transfer_usdc(
                destination=reservation["destination"],
                amount_minor=reservation["amount_minor"],
                network=reservation["network"],
            )
            self.store.mark_uncertain(reservation_id, tx_hash=str(tx_hash))
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
        try:
            gas_recorded = await self._record_gas_cost(reservation, str(tx_hash))
        except Exception as exc:
            return {"reservation_id": reservation_id, "status": "settled",
                    "tx_hash": str(tx_hash), "gas_cost_status": "pending",
                    "gas_cost_reason": str(exc)}
        return {"reservation_id": reservation_id, "status": "settled",
                "tx_hash": str(tx_hash),
                "gas_cost_status": "recorded" if gas_recorded else "pending"}

    async def reconcile(self, reservation_id: str, *, tx_hash: str | None = None) -> dict:
        """Verify a previously held payment; never broadcasts or retries it."""
        reservation = self._reservation(reservation_id)
        if not reservation:
            raise ValueError("spend reservation not found")
        if reservation["status"] not in {"uncertain", "broadcast"}:
            raise ValueError("only an uncertain or broadcast payment can be reconciled")
        known_hash = reservation["tx_hash"]
        if tx_hash and known_hash and tx_hash != known_hash:
            raise ValueError("reconciliation hash conflicts with the recorded transaction hash")
        selected_hash = known_hash or tx_hash
        if not selected_hash:
            raise ValueError("transaction hash is unknown; discover it from CDP or chain history before reconciliation")
        if not known_hash:
            self.store.mark_uncertain(reservation_id, tx_hash=selected_hash)
        wallet = self.store.treasury_wallet(reservation["network"], reservation["asset"])
        if not wallet:
            raise ValueError("collective treasury wallet is not registered")
        verified = await self.verifier.verify_transfer(
            network=reservation["network"], asset=reservation["asset"],
            tx_hash=selected_hash, source_address=wallet.address,
            destination_address=reservation["destination"],
            amount_minor=reservation["amount_minor"],
        )
        self.store.settle_spend(reservation_id, verified)
        try:
            gas_recorded = await self._record_gas_cost(reservation, selected_hash)
        except Exception as exc:
            return {"reservation_id": reservation_id, "status": "settled",
                    "tx_hash": selected_hash, "gas_cost_status": "pending",
                    "gas_cost_reason": str(exc)}
        return {"reservation_id": reservation_id, "status": "settled",
                "tx_hash": selected_hash,
                "gas_cost_status": "recorded" if gas_recorded else "pending"}

    async def reconcile_gas_cost(self, reservation_id: str) -> dict:
        """Reconcile fee valuation for an already-settled spend; never resends funds."""
        reservation = self._reservation(reservation_id)
        if not reservation or reservation["status"] != "settled" or not reservation["tx_hash"]:
            raise ValueError("gas reconciliation requires a settled spend with a known transaction hash")
        if self._gas_cost_recorded(reservation_id):
            return {"reservation_id": reservation_id, "gas_cost_status": "recorded"}
        recorded = await self._record_gas_cost(reservation, reservation["tx_hash"])
        return {"reservation_id": reservation_id,
                "gas_cost_status": "recorded" if recorded else "pending"}


__all__ = [
    "CollectiveTreasuryPaymentExecutor", "TreasuryTransferVerifier",
    "TreasuryGasFeeVerifier", "NativeGasPriceOracle",
]
