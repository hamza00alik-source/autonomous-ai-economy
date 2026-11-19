"""Independent-provider quorum wrapper for canonical EVM transfer verification."""
from __future__ import annotations

from typing import Sequence

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
                heights.append(provider.finalized_block_number())
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
                votes[bool(provider.is_transfer_canonical(**kwargs))] += 1
            except Exception as exc:
                errors.append(exc)
        if votes[True] >= self.quorum:
            return True
        if votes[False] >= self.quorum:
            return False
        raise EVMRPCError(
            f"RPC providers disagree or are unavailable; votes={votes}, quorum={self.quorum}"
        ) from (errors[0] if errors else None)
