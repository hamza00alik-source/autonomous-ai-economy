"""Finality-aware incoming token monitor with replay and reorg protection.

The chain adapter is untrusted at the type boundary: every observation is checked
against configured network/asset/token and participant wallet addresses. Only
canonical, finalized observations meeting the configured confirmation threshold
are credited. This module does not connect to an RPC provider itself.
"""
from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Protocol

from .agent_finance import AgentFinanceStore, VerifiedTransfer


@dataclass(frozen=True)
class MonitoredAsset:
    network: str
    asset: str
    token_contract: str
    min_confirmations: int

    def __post_init__(self) -> None:
        if not all(isinstance(v, str) and v.strip() for v in
                   (self.network, self.asset, self.token_contract)):
            raise ValueError("network, asset and token_contract are required")
        if (isinstance(self.min_confirmations, bool)
                or not isinstance(self.min_confirmations, int)
                or self.min_confirmations < 1):
            raise ValueError("min_confirmations must be a positive integer")


@dataclass(frozen=True)
class ChainTransferObservation:
    network: str
    asset: str
    token_contract: str
    tx_hash: str
    transfer_ref: str
    source: str
    destination: str
    amount_minor: int
    block_number: int
    block_hash: str
    confirmations: int
    canonical: bool
    finalized: bool
    block_timestamp: str


@dataclass(frozen=True)
class TransferPage:
    transfers: tuple[ChainTransferObservation, ...]
    next_cursor: str | None
    has_more: bool | None = None


class ChainTransferSource(Protocol):
    """Read-only chain adapter; implementation must derive canonicality/finality."""

    def fetch_transfers(self, *, network: str, token_contract: str,
                        addresses: tuple[str, ...], cursor: str | None) -> TransferPage:
        ...


class ChainMonitor:
    """Poll verified chain observations and credit agent wallets exactly once.

    The monitor shares the finance SQLite database so event state and accounting
    writes can be made transactionally. A provider adapter must not trust webhook
    payloads alone: it must independently query chain/RPC state.
    """

    def __init__(self, finance: AgentFinanceStore, source: ChainTransferSource,
                 asset: MonitoredAsset, *,
                 period_resolver: Callable[[str], str] | None = None) -> None:
        self.finance = finance
        self.source = source
        self.asset = asset
        self.period_resolver = period_resolver
        self.path = finance.path
        with closing(self._connect()) as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS chain_monitor_cursors (
                    network TEXT NOT NULL,
                    token_contract TEXT NOT NULL,
                    cursor TEXT,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY(network, token_contract)
                );
                CREATE TABLE IF NOT EXISTS chain_monitor_events (
                    network TEXT NOT NULL,
                    tx_hash TEXT NOT NULL,
                    transfer_ref TEXT NOT NULL,
                    participant_id TEXT NOT NULL,
                    asset TEXT NOT NULL,
                    token_contract TEXT NOT NULL,
                    source_address TEXT NOT NULL,
                    destination_address TEXT NOT NULL,
                    amount_minor INTEGER NOT NULL,
                    block_number INTEGER NOT NULL,
                    block_hash TEXT NOT NULL,
                    confirmations INTEGER NOT NULL,
                    period_id TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN
                        ('observed','credited','orphaned','reorg_alert')),
                    resolution_note TEXT,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY(network, tx_hash, transfer_ref)
                );
                CREATE INDEX IF NOT EXISTS idx_chain_monitor_status
                    ON chain_monitor_events(participant_id, status);
            """)

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=15, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=15000")
        return db

    def _wallet_owners(self) -> dict[str, str]:
        with closing(self._connect()) as db:
            rows = db.execute(
                """SELECT participant_id,address FROM finance_wallets
                   WHERE role='agent' AND network=? AND asset=?""",
                (self.asset.network, self.asset.asset.upper()),
            ).fetchall()
        return {row["address"]: row["participant_id"] for row in rows}

    def _validate(self, item: ChainTransferObservation) -> None:
        if not isinstance(item, ChainTransferObservation):
            raise ValueError("chain source returned an invalid observation")
        if (item.network != self.asset.network
                or item.asset.upper() != self.asset.asset.upper()
                or item.token_contract.lower() != self.asset.token_contract.lower()):
            raise ValueError("observation network, asset or token contract mismatch")
        for value in (item.tx_hash, item.transfer_ref, item.source,
                      item.destination, item.block_hash):
            if not isinstance(value, str) or not value.strip():
                raise ValueError("transfer identity, addresses and block hash are required")
        for field, value, minimum in (
            ("amount_minor", item.amount_minor, 1),
            ("block_number", item.block_number, 0),
            ("confirmations", item.confirmations, 0),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
                raise ValueError(f"{field} is invalid")
        if not isinstance(item.canonical, bool) or not isinstance(item.finalized, bool):
            raise ValueError("canonical and finalized flags must be booleans")
        if not isinstance(item.block_timestamp, str) or not item.block_timestamp.strip():
            raise ValueError("block_timestamp must be an ISO-8601 timestamp")
        try:
            parsed_timestamp = datetime.fromisoformat(item.block_timestamp.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("block_timestamp must be an ISO-8601 timestamp") from exc
        if parsed_timestamp.tzinfo is None:
            raise ValueError("block_timestamp must include a timezone offset")

    def poll_once(self, *, period_id: str) -> dict[str, int | str | None]:
        if not isinstance(period_id, str) or not period_id.strip():
            raise ValueError("period_id is required")
        owners = self._wallet_owners()
        if not owners:
            return {"fetched": 0, "credited": 0, "pending": 0,
                    "orphaned": 0, "reorg_alerts": 0, "next_cursor": None}
        with closing(self._connect()) as db:
            row = db.execute(
                """SELECT cursor FROM chain_monitor_cursors
                   WHERE network=? AND token_contract=?""",
                (self.asset.network, self.asset.token_contract),
            ).fetchone()
        cursor = row["cursor"] if row else None
        page = self.source.fetch_transfers(
            network=self.asset.network, token_contract=self.asset.token_contract,
            addresses=tuple(sorted(owners)), cursor=cursor,
        )
        if not isinstance(page, TransferPage):
            raise ValueError("chain source returned an invalid page")
        counts = {"fetched": len(page.transfers), "credited": 0, "pending": 0,
                  "orphaned": 0, "reorg_alerts": 0}
        for item in page.transfers:
            self._validate(item)
            event_period = self.period_resolver(item.block_timestamp) if self.period_resolver else period_id
            if not isinstance(event_period, str) or not event_period.strip():
                raise ValueError("period resolver must return a non-empty accounting period")
            participant_id = owners.get(item.destination)
            if not participant_id:
                continue
            with closing(self._connect()) as db:
                db.execute("BEGIN IMMEDIATE")
                old = db.execute(
                    """SELECT * FROM chain_monitor_events
                       WHERE network=? AND tx_hash=? AND transfer_ref=?""",
                    (item.network, item.tx_hash, item.transfer_ref),
                ).fetchone()
                if not item.canonical:
                    status = "reorg_alert" if old and old["status"] == "credited" else "orphaned"
                    db.execute(
                        """INSERT INTO chain_monitor_events
                           (network,tx_hash,transfer_ref,participant_id,asset,token_contract,
                            source_address,destination_address,amount_minor,block_number,block_hash,
                            confirmations,period_id,status)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                           ON CONFLICT(network,tx_hash,transfer_ref) DO UPDATE SET
                             status=excluded.status,updated_at=CURRENT_TIMESTAMP""",
                        (item.network,item.tx_hash,item.transfer_ref,participant_id,
                         self.asset.asset.upper(),self.asset.token_contract,item.source,
                         item.destination,item.amount_minor,item.block_number,item.block_hash,
                         item.confirmations,event_period,status),
                    )
                    db.commit()
                    counts["reorg_alerts" if status == "reorg_alert" else "orphaned"] += 1
                    continue
                if old and old["status"] in {"orphaned", "reorg_alert"}:
                    # A previously orphaned log reappearing is not auto-credited:
                    # it needs a fresh, canonical block identity and operator review.
                    db.execute(
                        """UPDATE chain_monitor_events SET status='reorg_alert',
                           updated_at=CURRENT_TIMESTAMP
                           WHERE network=? AND tx_hash=? AND transfer_ref=?""",
                        (item.network,item.tx_hash,item.transfer_ref),
                    )
                    db.commit()
                    counts["reorg_alerts"] += 1
                    continue
                if not item.finalized or item.confirmations < self.asset.min_confirmations:
                    db.execute(
                        """INSERT INTO chain_monitor_events
                           (network,tx_hash,transfer_ref,participant_id,asset,token_contract,
                            source_address,destination_address,amount_minor,block_number,block_hash,
                            confirmations,period_id,status)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,'observed')
                           ON CONFLICT(network,tx_hash,transfer_ref) DO UPDATE SET
                             confirmations=excluded.confirmations,updated_at=CURRENT_TIMESTAMP""",
                        (item.network,item.tx_hash,item.transfer_ref,participant_id,
                         self.asset.asset.upper(),self.asset.token_contract,item.source,
                         item.destination,item.amount_minor,item.block_number,item.block_hash,
                         item.confirmations,event_period),
                    )
                    db.commit()
                    counts["pending"] += 1
                    continue
                if old and old["status"] == "credited":
                    if (old["block_hash"] != item.block_hash
                            or old["amount_minor"] != item.amount_minor
                            or old["destination_address"] != item.destination):
                        db.execute(
                            """UPDATE chain_monitor_events SET status='reorg_alert',
                               updated_at=CURRENT_TIMESTAMP
                               WHERE network=? AND tx_hash=? AND transfer_ref=?""",
                            (item.network,item.tx_hash,item.transfer_ref),
                        )
                        db.commit()
                        counts["reorg_alerts"] += 1
                    else:
                        db.commit()
                    continue
                closed_period = db.execute(
                    """SELECT 1 FROM profit_periods
                       WHERE agent_id=? AND network=? AND asset=? AND period_id=?""",
                    (participant_id, item.network, self.asset.asset.upper(), event_period),
                ).fetchone()
                if closed_period:
                    db.rollback()
                    raise ValueError(
                        "finalized transfer belongs to a closed profit period; "
                        "route it to a separately reconciled adjustment period"
                    )
                try:
                    # Keep the finance write and monitor status transition atomic.
                    db.execute(
                        """INSERT INTO finance_events
                           (event_id,participant_id,event_type,network,asset,amount_minor,
                            tx_hash,transfer_ref,period_id,created_at)
                           VALUES(?,?,'income',?,?,?,?,?,?,CURRENT_TIMESTAMP)""",
                        ("chain_" + item.tx_hash + "_" + item.transfer_ref,
                         participant_id,item.network,self.asset.asset.upper(),
                         item.amount_minor,item.tx_hash,item.transfer_ref,event_period),
                    )
                except sqlite3.IntegrityError:
                    existing = db.execute(
                        """SELECT participant_id,event_type,amount_minor,period_id
                           FROM finance_events WHERE network=? AND tx_hash=? AND transfer_ref=?""",
                        (item.network,item.tx_hash,item.transfer_ref),
                    ).fetchone()
                    if (not existing or existing["participant_id"] != participant_id
                            or existing["event_type"] != "income"
                            or existing["amount_minor"] != item.amount_minor
                            or existing["period_id"] != event_period):
                        db.rollback()
                        raise ValueError("transfer conflicts with an existing finance event")
                db.execute(
                    """INSERT INTO chain_monitor_events
                       (network,tx_hash,transfer_ref,participant_id,asset,token_contract,
                        source_address,destination_address,amount_minor,block_number,block_hash,
                        confirmations,period_id,status)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,'credited')
                       ON CONFLICT(network,tx_hash,transfer_ref) DO UPDATE SET
                         confirmations=excluded.confirmations,status='credited',
                         updated_at=CURRENT_TIMESTAMP""",
                    (item.network,item.tx_hash,item.transfer_ref,participant_id,
                     self.asset.asset.upper(),self.asset.token_contract,item.source,
                     item.destination,item.amount_minor,item.block_number,item.block_hash,
                     item.confirmations,event_period),
                )
                db.commit()
                counts["credited"] += 1

        with closing(self._connect()) as db:
            db.execute(
                """INSERT INTO chain_monitor_cursors(network,token_contract,cursor)
                   VALUES(?,?,?) ON CONFLICT(network,token_contract) DO UPDATE SET
                   cursor=excluded.cursor,updated_at=CURRENT_TIMESTAMP""",
                (self.asset.network,self.asset.token_contract,page.next_cursor),
            )
        return {**counts, "next_cursor": page.next_cursor}

    def list_reorg_alerts(self, *, limit: int = 100) -> list[dict]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        with closing(self._connect()) as db:
            rows = db.execute(
                """SELECT c.* FROM chain_monitor_events c
                   WHERE c.status='reorg_alert'
                     AND NOT EXISTS (
                       SELECT 1 FROM reorg_alert_resolutions r
                       WHERE r.network=c.network AND r.tx_hash=c.tx_hash
                         AND r.transfer_ref=c.transfer_ref
                     )
                   ORDER BY c.updated_at LIMIT ?""", (limit,)
            ).fetchall()
        return [dict(row) for row in rows]

    def resolve_reorg_alert(self, network: str, tx_hash: str, transfer_ref: str,
                             *, resolution_note: str) -> None:
        """Record an operator note without clearing the safety hold.

        This does not reverse an already-credited receipt. Keep the alert active
        until a separately audited compensating ledger adjustment is implemented.
        """
        if not isinstance(resolution_note, str) or len(resolution_note.strip()) < 12:
            raise ValueError("resolution_note must explain the reconciliation (12+ characters)")
        with closing(self._connect()) as db:
            cur = db.execute(
                """UPDATE chain_monitor_events SET resolution_note=?,
                   updated_at=CURRENT_TIMESTAMP
                   WHERE network=? AND tx_hash=? AND transfer_ref=? AND status='reorg_alert'""",
                (resolution_note.strip(),network,tx_hash,transfer_ref),
            )
            if cur.rowcount != 1:
                raise ValueError("unresolved reorg alert not found")
