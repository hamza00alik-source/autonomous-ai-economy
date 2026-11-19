"""Rolling reconciliation of credited chain transfers against canonical history."""
from __future__ import annotations

from contextlib import closing
from typing import Protocol

from .agent_finance import AgentFinanceStore


class CanonicalTransferVerifier(Protocol):
    def finalized_block_number(self) -> int: ...
    def is_transfer_canonical(
        self, *, network: str, token_contract: str, tx_hash: str,
        transfer_ref: str, expected_block_number: int, expected_block_hash: str,
        source: str, destination: str, amount_minor: int,
    ) -> bool: ...


class ChainReorgReconciler:
    """Recheck credited transfers in a rolling finalized-block window.

    RPC uncertainty raises and leaves state unchanged. Only a definitive
    canonical-history mismatch creates a reorg alert.
    """

    def __init__(self, finance: AgentFinanceStore, verifier: CanonicalTransferVerifier,
                 *, network: str, token_contract: str, lookback_blocks: int = 256,
                 batch_size: int = 500) -> None:
        if not network or not token_contract:
            raise ValueError("network and token_contract are required")
        if isinstance(lookback_blocks, bool) or not isinstance(lookback_blocks, int) or lookback_blocks < 1:
            raise ValueError("lookback_blocks must be a positive integer")
        if isinstance(batch_size, bool) or not isinstance(batch_size, int) or not 1 <= batch_size <= 5000:
            raise ValueError("batch_size must be between 1 and 5000")
        self.finance, self.verifier = finance, verifier
        self.network, self.token_contract = network, token_contract.lower()
        self.lookback_blocks, self.batch_size = lookback_blocks, batch_size

    def reconcile_once(self) -> dict[str, int]:
        finalized = self.verifier.finalized_block_number()
        if isinstance(finalized, bool) or not isinstance(finalized, int) or finalized < 0:
            raise ValueError("verifier returned invalid finalized block")
        floor = max(0, finalized - self.lookback_blocks + 1)
        with closing(self.finance._connect()) as db:
            rows = db.execute(
                """SELECT network,tx_hash,transfer_ref,source_address,destination_address,
                          amount_minor,block_number,block_hash
                   FROM chain_monitor_events
                   WHERE network=? AND lower(token_contract)=? AND status='credited'
                     AND block_number>=?
                   ORDER BY block_number DESC LIMIT ?""",
                (self.network, self.token_contract, floor, self.batch_size),
            ).fetchall()
        checked = alerts = 0
        for row in rows:
            checked += 1
            canonical = self.verifier.is_transfer_canonical(
                network=row["network"], token_contract=self.token_contract,
                tx_hash=row["tx_hash"], transfer_ref=row["transfer_ref"],
                expected_block_number=row["block_number"],
                expected_block_hash=row["block_hash"], source=row["source_address"],
                destination=row["destination_address"], amount_minor=row["amount_minor"],
            )
            if not canonical:
                with closing(self.finance._connect()) as db:
                    cur = db.execute(
                        """UPDATE chain_monitor_events SET status='reorg_alert',
                           updated_at=CURRENT_TIMESTAMP
                           WHERE network=? AND tx_hash=? AND transfer_ref=? AND status='credited'""",
                        (row["network"], row["tx_hash"], row["transfer_ref"]),
                    )
                    alerts += cur.rowcount
        return {"checked": checked, "reorg_alerts": alerts, "from_block": floor,
                "finalized_block": finalized}
