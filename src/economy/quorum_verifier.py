"""Independent-provider quorum wrapper for canonical EVM transfer verification."""
from __future__ import annotations

import asyncio
from typing import Sequence

from .agent_finance import VerifiedTransfer
from .evm_rpc import EVMJSONRPCSource, EVMRPCError


class QuorumEVMVerifier:
    """Require a strict provider quorum for finalized height and transfer truth.

    A provider error is not a negative vote. If neither outcome reaches quorum,
    the operation fails closed and callers must retry without changing ledger state.
    """

    def __init__(self, providers: Sequence[EVMJSONRPCSource], *, quorum: int | None = None) -> None:
        self.providers = tuple(providers)
        if len(self.providers) < 2:
            raise ValueError("at least two independent RPC providers are required")
        if len({p.config.chain_id for p in self.providers}) != 1:
            raise ValueError("all RPC providers must target the same chain ID")
        if len({p.config.network for p in self.providers}) != 1:
            raise ValueError("all RPC providers must target the same network")
        if len({p.config.token_contract.lower() for p in self.providers}) != 1:
            raise ValueError("all RPC providers must target the same token contract")
        if len({id(provider) for provider in self.providers}) != len(self.providers):
            raise ValueError("the same RPC provider cannot count as multiple sources")
        configured_urls = [
            getattr(getattr(provider, "config", None), "rpc_url", None)
            for provider in self.providers
        ]
        if all(isinstance(url, str) and url for url in configured_urls):
            normalized_urls = {url.rstrip("/").lower() for url in configured_urls}
            if len(normalized_urls) != len(configured_urls):
                raise ValueError("RPC provider URLs must be distinct")
        minimum_majority = len(self.providers) // 2 + 1
        self.quorum = quorum if quorum is not None else minimum_majority
        if (isinstance(self.quorum, bool) or not isinstance(self.quorum, int)
                or not minimum_majority <= self.quorum <= len(self.providers)):
            raise ValueError("quorum must be a strict majority of independent providers")

    def finalized_block_number(self) -> int:
        heights = []
        errors = []
        for provider in self.providers:
            try:
                height = provider.finalized_block_number()
                if isinstance(height, bool) or not isinstance(height, int) or height < 0:
                    raise EVMRPCError("provider returned an invalid finalized block height")
                heights.append(height)
            except Exception as exc:
                errors.append(exc)
        if len(heights) < self.quorum:
            raise EVMRPCError(f"only {len(heights)} providers supplied finalized height; quorum is {self.quorum}") from (errors[0] if errors else None)
        # Use the quorum-th highest height so at least quorum providers have
        # finalized this block. Requiring each provider to support the exact
        # same height would make a slower but healthy node stall the scan.
        heights.sort(reverse=True)
        return heights[self.quorum - 1]

    def is_transfer_canonical(self, **kwargs) -> bool:
        votes = {True: 0, False: 0}
        errors = []
        for provider in self.providers:
            try:
                result = provider.is_transfer_canonical(**kwargs)
                if not isinstance(result, bool):
                    raise EVMRPCError("provider returned a non-boolean canonicality result")
                votes[result] += 1
            except Exception as exc:
                errors.append(exc)
        if votes[True] >= self.quorum:
            return True
        if votes[False] >= self.quorum:
            return False
        raise EVMRPCError(
            f"RPC providers disagree or are unavailable; votes={votes}, quorum={self.quorum}"
        ) from (errors[0] if errors else None)

    def _verify_transfer_quorum(self, *, network: str, asset: str, tx_hash: str,
                                source_address: str, destination_address: str,
                                amount_minor: int) -> VerifiedTransfer:
        votes: dict[tuple, list[VerifiedTransfer]] = {}
        errors = []
        for provider in self.providers:
            try:
                transfer = provider.verify_transfer(
                    network=network, asset=asset, tx_hash=tx_hash,
                    source_address=source_address,
                    destination_address=destination_address,
                    amount_minor=amount_minor,
                )
                if not isinstance(transfer, VerifiedTransfer) or transfer.verified is not True:
                    raise EVMRPCError("provider returned invalid or unverified transfer evidence")
                if (transfer.network != network or transfer.asset.upper() != asset.upper()
                        or transfer.tx_hash.lower() != tx_hash.lower()
                        or transfer.source.lower() != source_address.lower()
                        or transfer.destination.lower() != destination_address.lower()
                        or transfer.amount_minor != amount_minor):
                    raise EVMRPCError("provider transfer evidence does not match requested payout")
                fingerprint = (
                    transfer.network, transfer.asset.upper(), transfer.tx_hash.lower(),
                    transfer.transfer_ref, transfer.source.lower(),
                    transfer.destination.lower(), transfer.amount_minor,
                )
                votes.setdefault(fingerprint, []).append(transfer)
            except Exception as exc:
                errors.append(exc)
        winners = [items for items in votes.values() if len(items) >= self.quorum]
        if len(winners) != 1:
            raise EVMRPCError(
                f"RPC providers did not reach transfer-verification quorum; "
                f"matching votes={[len(items) for items in votes.values()]}, "
                f"quorum={self.quorum}"
            ) from (errors[0] if errors else None)
        return max(winners[0], key=lambda item: item.confirmations)

    async def verify_transfer(self, *, network: str, asset: str, tx_hash: str,
                              source_address: str, destination_address: str,
                              amount_minor: int) -> VerifiedTransfer:
        """Verify an exact payout transfer on a strict majority of independent RPCs."""
        return await asyncio.to_thread(
            self._verify_transfer_quorum,
            network=network, asset=asset, tx_hash=tx_hash,
            source_address=source_address, destination_address=destination_address,
            amount_minor=amount_minor,
        )
