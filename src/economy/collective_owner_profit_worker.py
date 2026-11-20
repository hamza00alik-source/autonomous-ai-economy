"""Verified owner-profit payouts from the one shared collective treasury.

This worker pays the owner's already-allocated 50% net-profit share from the
shared treasury wallet. It is separate from overflow sweeps and never uses the
legacy per-agent wallet ledger.
"""
from __future__ import annotations

from typing import Protocol

from .agent_finance import VerifiedTransfer
from .collective_treasury import CollectiveTreasuryStore


class CollectiveProfitSigner(Protocol):
    async def transfer_usdc(self, *, destination: str, amount_minor: int,
                            network: str = "base-sepolia") -> str: ...


class CollectiveProfitVerifier(Protocol):
    async def verify_transfer(self, *, network: str, asset: str, tx_hash: str,
                               source_address: str, destination_address: str,
                               amount_minor: int) -> VerifiedTransfer: ...


class CollectiveOwnerProfitPayoutWorker:
    """Drain owner-share obligations with exact verification and no blind retry."""

    def __init__(self, store: CollectiveTreasuryStore, signer: CollectiveProfitSigner,
                 verifier: CollectiveProfitVerifier) -> None:
        self.store, self.signer, self.verifier = store, signer, verifier

    async def execute(self, payout_id: str) -> dict:
        payout = self.store.get_owner_profit_payout(payout_id)
        if not payout:
            raise ValueError("owner profit payout not found")
        if payout["status"] != "reserved":
            raise ValueError("only a fresh reserved owner profit payout can be submitted")
        wallet = self.store.treasury_wallet(payout["network"], payout["asset"])
        if not wallet:
            raise ValueError("collective treasury wallet is not registered")
        if not self.store.claim_owner_profit_payout(payout_id):
            raise ValueError("owner profit payout was already claimed")
        try:
            tx_hash = await self.signer.transfer_usdc(
                destination=payout["destination_address"],
                amount_minor=int(payout["amount_minor"]),
                network=payout["network"],
            )
            if (not isinstance(tx_hash, str) or len(tx_hash) != 66
                    or not tx_hash.startswith("0x")):
                raise ValueError("signer did not return a valid transaction hash")
            self.store.record_owner_profit_payout_tx(payout_id, tx_hash)
        except Exception:
            return {
                "payout_id": payout_id, "status": "uncertain",
                "reason": "provider outcome must be reconciled before any retry",
            }
        return await self.reconcile(payout_id, tx_hash=tx_hash)

    async def reconcile(self, payout_id: str, *, tx_hash: str | None = None) -> dict:
        """Verify an uncertain payout without broadcasting or retrying it."""
        payout = self.store.get_owner_profit_payout(payout_id)
        if not payout:
            raise ValueError("owner profit payout not found")
        if payout["status"] != "uncertain":
            raise ValueError("only an uncertain owner profit payout can be reconciled")
        known_hash = payout.get("tx_hash")
        if tx_hash and known_hash and tx_hash.lower() != known_hash.lower():
            raise ValueError("reconciliation hash conflicts with recorded owner payout hash")
        selected_hash = known_hash or tx_hash
        if not selected_hash:
            return {
                "payout_id": payout_id, "status": "uncertain",
                "reason": "transaction hash is unknown; reconcile provider/chain history before retry",
            }
        if not known_hash:
            self.store.record_owner_profit_payout_tx(payout_id, selected_hash)
        wallet = self.store.treasury_wallet(payout["network"], payout["asset"])
        if not wallet:
            raise ValueError("collective treasury wallet is not registered")
        try:
            verified = await self.verifier.verify_transfer(
                network=payout["network"], asset=payout["asset"],
                tx_hash=selected_hash, source_address=wallet.address,
                destination_address=payout["destination_address"],
                amount_minor=int(payout["amount_minor"]),
            )
            if not isinstance(verified, VerifiedTransfer):
                raise ValueError("chain verifier returned invalid transfer evidence")
            self.store.settle_owner_profit_payout(payout_id, verified)
        except Exception as exc:
            return {
                "payout_id": payout_id, "status": "uncertain",
                "tx_hash": selected_hash, "reason": str(exc)[:240],
            }
        return {
            "payout_id": payout_id, "status": "settled", "tx_hash": selected_hash,
            "amount_minor": int(payout["amount_minor"]),
            "destination_address": payout["destination_address"],
        }

    async def run_once(self, *, network: str, asset: str = "USDC",
                       limit: int = 25) -> dict:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 999:
            raise ValueError("limit must be an integer between 1 and 999")
        closes = self.store.list_unsettled_owner_profit_closes(network, asset, limit)
        results = []
        blocked = 0
        for close in closes:
            try:
                payout = self.store.reserve_owner_profit_payout(
                    close["agent_id"], network, asset, close["period_id"],
                    idempotency_key=(
                        f"owner-profit:{close['agent_id']}:{network}:"
                        f"{asset.upper()}:{close['period_id']}"
                    ),
                )
                if payout is None:
                    continue
                if payout["status"] == "reserved":
                    result = await self.execute(payout["payout_id"])
                elif payout["status"] == "uncertain":
                    result = await self.reconcile(payout["payout_id"])
                elif payout["status"] == "settled":
                    result = {"payout_id": payout["payout_id"], "status": "settled"}
                else:
                    result = {
                        "payout_id": payout["payout_id"], "status": "blocked",
                        "reason": "unknown owner payout state",
                    }
            except Exception as exc:
                blocked += 1
                result = {"period_id": close["period_id"], "status": "blocked",
                          "reason": str(exc)[:240]}
            if result["status"] == "blocked":
                blocked += 0 if result.get("reason") else 1
            results.append(result)

        outstanding = self.store.list_unsettled_owner_profit_closes(
            network, asset, limit + 1,
        )
        uncertain = sum(item["status"] == "uncertain" for item in results)
        settled = sum(item["status"] == "settled" for item in results)
        if blocked:
            status = "blocked"
        elif outstanding:
            status = "pending"
        else:
            status = "completed"
        return {
            "status": status, "settled": settled,
            "pending": max(uncertain, len(outstanding)),
            "blocked": blocked, "failed": blocked, "uncertain": uncertain,
            "backlog": len(outstanding) > limit, "results": results,
        }

    def runtime_callback(self, *, network: str, asset: str = "USDC",
                         limit: int = 25):
        """Return the zero-argument async callback required by Accounting runtime."""
        async def callback() -> dict:
            return await self.run_once(network=network, asset=asset, limit=limit)
        return callback


__all__ = ["CollectiveOwnerProfitPayoutWorker", "CollectiveProfitSigner",
           "CollectiveProfitVerifier"]
