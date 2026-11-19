"""Bounded worker for owner overflow sweeps from the shared treasury.

Overflow sweeps are not profit-share payouts. The worker submits only the exact
reserved amount to the owner destination captured in the reservation, records the
provider transaction hash before verification, and settles only independently
verified finalized transfer evidence. Ambiguous provider outcomes stay uncertain.
"""
from __future__ import annotations

from contextlib import closing
from typing import Protocol

from .agent_finance import VerifiedTransfer
from .collective_treasury import CollectiveTreasuryStore


class OwnerSweepVerifier(Protocol):
    async def verify_transfer(self, *, network: str, asset: str, tx_hash: str,
                              source_address: str, destination_address: str,
                              amount_minor: int) -> VerifiedTransfer:
        """Return exact finalized canonical transfer evidence or raise."""
        ...


class OwnerOverflowSweepWorker:
    """Submit and reconcile bounded owner overflow sweep reservations."""

    def __init__(self, store: CollectiveTreasuryStore, signer,
                 verifier: OwnerSweepVerifier) -> None:
        self.store = store
        self.signer = signer
        self.verifier = verifier

    async def execute(self, sweep_id: str) -> dict:
        sweep = self.store.get_owner_overflow_sweep(sweep_id)
        if not sweep:
            raise ValueError("owner overflow sweep not found")
        if sweep["status"] != "reserved":
            raise ValueError("only a fresh reserved owner overflow sweep can be submitted")
        wallet = self.store.treasury_wallet(sweep["network"], sweep["asset"])
        if not wallet:
            raise ValueError("collective treasury wallet is not registered")
        if not self.store.claim_owner_overflow_sweep(sweep_id):
            raise ValueError("owner overflow sweep was already claimed")
        try:
            tx_hash = await self.signer.transfer_usdc(
                destination=sweep["destination_address"],
                amount_minor=int(sweep["amount_minor"]),
                network=sweep["network"],
            )
            if not isinstance(tx_hash, str) or len(tx_hash) != 66 or not tx_hash.startswith("0x"):
                raise ValueError("signer did not return a valid transaction hash")
            self.store.record_owner_overflow_sweep_tx(sweep_id, tx_hash)
        except Exception:
            return {"sweep_id": sweep_id, "status": "uncertain",
                    "reason": "provider outcome must be reconciled before any retry"}
        return await self.reconcile(sweep_id, tx_hash=tx_hash)

    async def reconcile(self, sweep_id: str, *, tx_hash: str | None = None) -> dict:
        """Verify an uncertain sweep without broadcasting or retrying it."""
        sweep = self.store.get_owner_overflow_sweep(sweep_id)
        if not sweep:
            raise ValueError("owner overflow sweep not found")
        if sweep["status"] != "uncertain":
            raise ValueError("only an uncertain owner overflow sweep can be reconciled")
        known_hash = sweep.get("tx_hash")
        if tx_hash and known_hash and tx_hash.lower() != known_hash.lower():
            raise ValueError("reconciliation hash conflicts with the recorded transaction hash")
        selected_hash = known_hash or tx_hash
        if not selected_hash:
            raise ValueError("transaction hash is unknown; discover it from provider or chain history before reconciliation")
        if not known_hash:
            self.store.record_owner_overflow_sweep_tx(sweep_id, selected_hash)
        wallet = self.store.treasury_wallet(sweep["network"], sweep["asset"])
        if not wallet:
            raise ValueError("collective treasury wallet is not registered")
        try:
            verified = await self.verifier.verify_transfer(
                network=sweep["network"], asset=sweep["asset"],
                tx_hash=selected_hash, source_address=wallet.address,
                destination_address=sweep["destination_address"],
                amount_minor=int(sweep["amount_minor"]),
            )
            if not isinstance(verified, VerifiedTransfer):
                raise ValueError("chain verifier returned invalid transfer evidence")
            self.store.settle_owner_overflow_sweep(sweep_id, verified)
        except Exception as exc:
            return {"sweep_id": sweep_id, "status": "uncertain",
                    "tx_hash": selected_hash,
                    "reason": str(exc)[:240]}
        return {"sweep_id": sweep_id, "status": "settled",
                "tx_hash": selected_hash, "amount_minor": int(sweep["amount_minor"]),
                "destination_address": sweep["destination_address"]}

    async def run_once(self, *, network: str, asset: str = "USDC",
                       period_id: str, limit: int = 10) -> dict:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise ValueError("limit must be an integer between 1 and 100")
        with closing(self.store._connect()) as db:
            rows = db.execute(
                """SELECT sweep_id FROM treasury_owner_overflow_sweeps
                   WHERE network=? AND asset=? AND status='reserved'
                   ORDER BY created_at,sweep_id LIMIT ?""",
                (network, asset.upper(), limit),
            ).fetchall()
        results = []
        for row in rows:
            try:
                result = await self.execute(row["sweep_id"])
            except ValueError as exc:
                result = {"sweep_id": row["sweep_id"], "status": "skipped",
                          "reason": str(exc)[:240]}
            results.append(result)
        return {
            "examined": len(rows),
            "settled": sum(item["status"] == "settled" for item in results),
            "uncertain": sum(item["status"] == "uncertain" for item in results),
            "skipped": sum(item["status"] == "skipped" for item in results),
            "results": results,
        }


    async def run_cycle(self, *, network: str, asset: str = "USDC",
                        period_id: str, limit: int = 10) -> dict:
        """Create an idempotent reservation for detected excess, then process it.

        The runtime must run its independent balance reconciliation again after
        this callback before allowing ordinary agent spending.
        """
        capacity = self.store.shared_wallet_capacity(network, asset)
        if not capacity["over_cap"]:
            return {"status": "not_needed", "examined": 0, "settled": 0,
                    "uncertain": 0, "remaining_excess_minor": 0}
        self.store.reserve_owner_overflow_sweep(
            network, asset, period_id=period_id,
            idempotency_key=(
                f"owner-overflow:{network}:{asset.upper()}:{period_id}:"
                f"{capacity['balance_minor']}"
            ),
        )
        result = await self.run_once(
            network=network, asset=asset, period_id=period_id, limit=limit,
        )
        refreshed = self.store.shared_wallet_capacity(network, asset)
        result.update({
            "status": "settled" if not refreshed["over_cap"] else "pending",
            "remaining_excess_minor": refreshed["excess_minor"],
        })
        return result


    def runtime_callback(self, *, network: str, asset: str = "USDC",
                         period_id_provider, limit: int = 10):
        """Build the zero-argument callback expected by the Accounting runtime.

        The provider is evaluated for every cycle, so month boundaries are not
        captured as stale values when the supervised runtime keeps running.
        """
        if not callable(period_id_provider):
            raise TypeError("period_id_provider must be callable")

        async def callback() -> dict:
            period_id = period_id_provider()
            if not isinstance(period_id, str) or not period_id.strip():
                raise ValueError("period_id_provider must return a non-empty string")
            return await self.run_cycle(
                network=network, asset=asset, period_id=period_id, limit=limit,
            )

        return callback


__all__ = ["OwnerOverflowSweepWorker", "OwnerSweepVerifier"]
