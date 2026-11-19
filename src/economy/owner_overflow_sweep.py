"""Owner overflow sweeps for the single shared AAE treasury.

Only unallocated suspense funds above the wallet-wide USDC cap are eligible.
The worker never retries an ambiguous provider submission; it reconciles by
transaction hash and independently verified finalized chain evidence.
"""
from __future__ import annotations

from typing import Protocol

from .agent_finance import VerifiedTransfer
from .collective_treasury import CollectiveTreasuryStore


class OwnerSweepSigner(Protocol):
    async def transfer_usdc(self, *, destination: str, amount_minor: int,
                            network: str = "base-sepolia") -> str:
        """Submit one exact USDC transfer from the configured collective wallet."""
        ...


class OwnerSweepVerifier(Protocol):
    async def verify_transfer(self, *, network: str, asset: str, tx_hash: str,
                              source_address: str, destination_address: str,
                              amount_minor: int) -> VerifiedTransfer:
        """Return independently verified finalized transfer evidence."""
        ...


class OwnerOverflowSweepWorker:
    """Sweep excess unallocated USDC to the configured owner address.

    The owner destination is configured through the authenticated owner control
    plane. This worker is not exposed to agent capabilities. It must be run only
    after the host's ordinary chain reconciliation and reorg safety gates pass.
    """

    def __init__(self, store: CollectiveTreasuryStore, signer: OwnerSweepSigner,
                 verifier: OwnerSweepVerifier) -> None:
        self.store = store
        self.signer = signer
        self.verifier = verifier

    async def run_once(self, *, network: str, asset: str, period_id: str,
                       idempotency_key: str) -> dict:
        sweep = self.store.reserve_owner_overflow_sweep(
            network, asset, period_id=period_id, idempotency_key=idempotency_key
        )
        if sweep is None:
            return {"status": "no_sweep_required_or_no_unallocated_excess"}
        if sweep["status"] != "reserved":
            return {"sweep_id": sweep["sweep_id"], "status": sweep["status"],
                    "reason": "existing sweep must be reconciled; it will not be resubmitted"}
        if not self.store.claim_owner_overflow_sweep(sweep["sweep_id"]):
            current = self.store.get_owner_overflow_sweep(sweep["sweep_id"])
            return {"sweep_id": sweep["sweep_id"],
                    "status": current["status"] if current else "unknown",
                    "reason": "sweep was already claimed"}
        wallet = self.store.treasury_wallet(network, asset)
        if not wallet:
            return {"sweep_id": sweep["sweep_id"], "status": "uncertain",
                    "reason": "collective treasury wallet is not registered"}
        try:
            tx_hash = await self.signer.transfer_usdc(
                destination=sweep["destination_address"],
                amount_minor=sweep["amount_minor"], network=network,
            )
        except Exception as exc:
            return {"sweep_id": sweep["sweep_id"], "status": "uncertain",
                    "reason": "provider outcome must be discovered before retry",
                    "detail": str(exc)}
        try:
            self.store.record_owner_overflow_sweep_tx(sweep["sweep_id"], str(tx_hash))
            verified = await self.verifier.verify_transfer(
                network=network, asset=asset, tx_hash=str(tx_hash),
                source_address=wallet.address,
                destination_address=sweep["destination_address"],
                amount_minor=sweep["amount_minor"],
            )
            self.store.settle_owner_overflow_sweep(sweep["sweep_id"], verified)
        except Exception as exc:
            return {"sweep_id": sweep["sweep_id"], "status": "uncertain",
                    "tx_hash": str(tx_hash),
                    "reason": "sweep is not settled until exact finalized transfer verification",
                    "detail": str(exc)}
        return {"sweep_id": sweep["sweep_id"], "status": "settled",
                "tx_hash": str(tx_hash), "amount_minor": sweep["amount_minor"],
                "destination_address": sweep["destination_address"],
                "accounting_reason": "owner_overflow_sweep"}

    async def reconcile(self, sweep_id: str, *, tx_hash: str | None = None) -> dict:
        """Reconcile a prior uncertain sweep without broadcasting another transfer."""
        sweep = self.store.get_owner_overflow_sweep(sweep_id)
        if not sweep:
            raise ValueError("owner overflow sweep not found")
        if sweep["status"] not in {"uncertain", "reserved"}:
            return {"sweep_id": sweep_id, "status": sweep["status"]}
        known_hash = sweep["tx_hash"]
        if tx_hash and known_hash and tx_hash.lower() != known_hash.lower():
            raise ValueError("reconciliation hash conflicts with the recorded sweep hash")
        selected_hash = known_hash or tx_hash
        if not selected_hash:
            raise ValueError("transaction hash is unknown; discover it from provider or chain history before reconciliation")
        if not known_hash:
            if sweep["status"] == "reserved":
                if not self.store.claim_owner_overflow_sweep(sweep_id):
                    raise ValueError("sweep could not be claimed for reconciliation")
            self.store.record_owner_overflow_sweep_tx(sweep_id, selected_hash)
        wallet = self.store.treasury_wallet(sweep["network"], sweep["asset"])
        if not wallet:
            raise ValueError("collective treasury wallet is not registered")
        verified = await self.verifier.verify_transfer(
            network=sweep["network"], asset=sweep["asset"], tx_hash=selected_hash,
            source_address=wallet.address,
            destination_address=sweep["destination_address"],
            amount_minor=sweep["amount_minor"],
        )
        self.store.settle_owner_overflow_sweep(sweep_id, verified)
        return {"sweep_id": sweep_id, "status": "settled",
                "tx_hash": selected_hash, "amount_minor": sweep["amount_minor"],
                "accounting_reason": "owner_overflow_sweep"}


__all__ = ["OwnerOverflowSweepWorker", "OwnerSweepSigner", "OwnerSweepVerifier"]
