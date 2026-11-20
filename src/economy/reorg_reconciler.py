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
        with closing(self.finance._connect()) as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS chain_reorg_reconcile_cursors (
                    network TEXT NOT NULL, token_contract TEXT NOT NULL,
                    block_number INTEGER NOT NULL, tx_hash TEXT NOT NULL,
                    transfer_ref TEXT NOT NULL, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY(network, token_contract)
                )
            """)

    def reconcile_once(self) -> dict[str, int]:
        finalized = self.verifier.finalized_block_number()
        if isinstance(finalized, bool) or not isinstance(finalized, int) or finalized < 0:
            raise ValueError("verifier returned invalid finalized block")
        floor = max(0, finalized - self.lookback_blocks + 1)
        with closing(self.finance._connect()) as db:
            cursor = db.execute(
                """SELECT block_number,tx_hash,transfer_ref FROM chain_reorg_reconcile_cursors
                   WHERE network=? AND token_contract=?""",
                (self.network, self.token_contract),
            ).fetchone()
            last = (cursor["block_number"], cursor["tx_hash"], cursor["transfer_ref"]) if cursor else None
            if last and last[0] < floor:
                last = None
            if last:
                rows = db.execute(
                    """SELECT network,tx_hash,transfer_ref,source_address,destination_address,
                              amount_minor,block_number,block_hash
                       FROM chain_monitor_events
                       WHERE network=? AND lower(token_contract)=? AND status='credited'
                         AND block_number>=? AND
                         (block_number>? OR (block_number=? AND
                          (tx_hash>? OR (tx_hash=? AND transfer_ref>?))))
                       ORDER BY block_number,tx_hash,transfer_ref LIMIT ?""",
                    (self.network,self.token_contract,floor,last[0],last[0],
                     last[1],last[1],last[2],self.batch_size + 1),
                ).fetchall()
            else:
                rows = db.execute(
                    """SELECT network,tx_hash,transfer_ref,source_address,destination_address,
                              amount_minor,block_number,block_hash
                       FROM chain_monitor_events
                       WHERE network=? AND lower(token_contract)=? AND status='credited'
                         AND block_number>=?
                       ORDER BY block_number,tx_hash,transfer_ref LIMIT ?""",
                    (self.network,self.token_contract,floor,self.batch_size + 1),
                ).fetchall()
        has_more = len(rows) > self.batch_size
        rows = rows[:self.batch_size]
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
            with closing(self.finance._connect()) as db:
                if not canonical:
                    cur = db.execute(
                        """UPDATE chain_monitor_events SET status='reorg_alert',
                           updated_at=CURRENT_TIMESTAMP
                           WHERE network=? AND tx_hash=? AND transfer_ref=? AND status='credited'""",
                        (row["network"], row["tx_hash"], row["transfer_ref"]),
                    )
                    alerts += cur.rowcount
                db.execute(
                    """INSERT INTO chain_reorg_reconcile_cursors
                       (network,token_contract,block_number,tx_hash,transfer_ref,updated_at)
                       VALUES(?,?,?,?,?,CURRENT_TIMESTAMP)
                       ON CONFLICT(network,token_contract) DO UPDATE SET
                       block_number=excluded.block_number,tx_hash=excluded.tx_hash,
                       transfer_ref=excluded.transfer_ref,updated_at=CURRENT_TIMESTAMP""",
                    (self.network,self.token_contract,row["block_number"],row["tx_hash"],row["transfer_ref"]),
                )
        if not has_more:
            with closing(self.finance._connect()) as db:
                db.execute("DELETE FROM chain_reorg_reconcile_cursors WHERE network=? AND token_contract=?",
                           (self.network,self.token_contract))
        return {"checked": checked, "reorg_alerts": alerts, "from_block": floor,
                "finalized_block": finalized, "has_more": has_more}
