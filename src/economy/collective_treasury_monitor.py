"""Finality-aware incoming receipts for the collective treasury.

Payment intents are attributed only when a pre-bound payer address and exact
amount identify one unique pending intent. Ambiguous deposits go to suspense.
The source must independently verify the configured chain/token and finality.
"""
from __future__ import annotations

import re
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Callable, Protocol, Sequence

from .agent_finance import VerifiedTransfer
from .chain_monitor import ChainTransferObservation, TransferPage
from .collective_treasury import CollectiveTreasuryStore

_ADDRESS = re.compile(r"^0x[0-9a-fA-F]{40}$")


class TreasuryReceiptSource(Protocol):
    def fetch_transfers(self, *, network: str, token_contract: str,
                        addresses: tuple[str, ...], cursor: str | None) -> TransferPage: ...


class QuorumTreasuryReceiptSource:
    """Require matching finalized transfer pages from independent RPC sources.

    This strict page quorum may temporarily stall when providers have different
    finalized heights. It fails closed rather than merging inconsistent pages.
    """

    def __init__(self, sources: Sequence[TreasuryReceiptSource], *, quorum: int | None = None) -> None:
        self.sources = tuple(sources)
        if len(self.sources) < 2:
            raise ValueError("at least two independent receipt sources are required")
        if len({id(source) for source in self.sources}) != len(self.sources):
            raise ValueError("the same receipt source cannot count as multiple providers")
        configured_urls = [
            getattr(getattr(source, "config", None), "rpc_url", None)
            for source in self.sources
        ]
        if all(isinstance(url, str) and url for url in configured_urls):
            normalized_urls = {url.rstrip("/").lower() for url in configured_urls}
            if len(normalized_urls) != len(configured_urls):
                raise ValueError("receipt RPC provider URLs must be distinct")
        minimum_majority = len(self.sources) // 2 + 1
        self.quorum = quorum if quorum is not None else minimum_majority
        if (isinstance(self.quorum, bool) or not isinstance(self.quorum, int)
                or not minimum_majority <= self.quorum <= len(self.sources)):
            raise ValueError("quorum must be a strict majority of independent sources")

    @staticmethod
    def _fingerprint(page: TransferPage) -> tuple:
        if not isinstance(page, TransferPage):
            raise ValueError("receipt source returned an invalid page")
        ordered = tuple(sorted(
            page.transfers,
            key=lambda item: (item.tx_hash, item.transfer_ref),
        ))
        return page.next_cursor, ordered

    def fetch_transfers(self, *, network: str, token_contract: str,
                        addresses: tuple[str, ...], cursor: str | None) -> TransferPage:
        votes: dict[tuple, list[TransferPage]] = {}
        errors = []
        for source in self.sources:
            try:
                page = source.fetch_transfers(
                    network=network, token_contract=token_contract,
                    addresses=addresses, cursor=cursor,
                )
                fingerprint = self._fingerprint(page)
                votes.setdefault(fingerprint, []).append(page)
            except Exception as exc:
                errors.append(exc)
        winners = [pages for pages in votes.values() if len(pages) >= self.quorum]
        if len(winners) != 1:
            raise RuntimeError(
                f"receipt RPC providers disagree or are unavailable; "
                f"matching page votes={[len(pages) for pages in votes.values()]}, "
                f"quorum={self.quorum}"
            ) from (errors[0] if errors else None)
        return winners[0][0]


class CollectiveTreasuryReceiptMonitor:
    """Ingest finalized transfers into the shared pool and route safe matches."""

    def __init__(self, store: CollectiveTreasuryStore, source: TreasuryReceiptSource,
                 *, token_contract: str,
                 period_resolver: Callable[[str], str] | None = None) -> None:
        if not isinstance(token_contract, str) or not _ADDRESS.fullmatch(token_contract):
            raise ValueError("token_contract must be a valid EVM address")
        self.store = store
        self.source = source
        self.token_contract = token_contract
        self.period_resolver = period_resolver
        with closing(store._connect()) as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS treasury_payer_bindings (
                    attribution_ref TEXT PRIMARY KEY,
                    payer_address TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS treasury_receipt_monitor_cursors (
                    network TEXT NOT NULL,
                    asset TEXT NOT NULL,
                    token_contract TEXT NOT NULL,
                    cursor TEXT,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY(network, asset, token_contract)
                );
                CREATE TABLE IF NOT EXISTS treasury_receipt_monitor_events (
                    network TEXT NOT NULL,
                    tx_hash TEXT NOT NULL,
                    transfer_ref TEXT NOT NULL,
                    block_hash TEXT NOT NULL,
                    block_number INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL CHECK(status IN ('allocated','unallocated','pending','orphaned')),
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY(network, tx_hash, transfer_ref)
                );
                CREATE TABLE IF NOT EXISTS treasury_reorg_alerts (
                    network TEXT NOT NULL,
                    asset TEXT NOT NULL,
                    tx_hash TEXT NOT NULL,
                    transfer_ref TEXT NOT NULL,
                    expected_block_hash TEXT NOT NULL,
                    observed_block_hash TEXT,
                    reason TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','resolved')),
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    resolved_at TEXT,
                    PRIMARY KEY(network, asset, tx_hash, transfer_ref)
                );
            """)
            columns = {row["name"] for row in db.execute(
                "PRAGMA table_info(treasury_receipt_monitor_events)"
            )}
            if "block_number" not in columns:
                db.execute(
                    "ALTER TABLE treasury_receipt_monitor_events "
                    "ADD COLUMN block_number INTEGER NOT NULL DEFAULT 0"
                )

    def _raise_reorg_alert(self, *, network: str, asset: str, tx_hash: str,
                           transfer_ref: str, expected_block_hash: str,
                           observed_block_hash: str | None, reason: str) -> None:
        with closing(self.store._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                """INSERT INTO treasury_reorg_alerts
                   (network,asset,tx_hash,transfer_ref,expected_block_hash,
                    observed_block_hash,reason)
                   VALUES(?,?,?,?,?,?,?)
                   ON CONFLICT(network,asset,tx_hash,transfer_ref) DO UPDATE SET
                     observed_block_hash=excluded.observed_block_hash,
                     reason=excluded.reason,status='open',resolved_at=NULL""",
                (network, asset.upper(), tx_hash, transfer_ref,
                 expected_block_hash, observed_block_hash, reason),
            )
            # A treasury-level canonicality incident freezes all agent spend policies
            # on the affected network/asset. Human review is required to resume.
            db.execute(
                """UPDATE treasury_receipt_monitor_events SET status='orphaned',
                   updated_at=CURRENT_TIMESTAMP
                   WHERE network=? AND tx_hash=? AND transfer_ref=?""",
                (network, tx_hash, transfer_ref),
            )
            db.execute(
                "UPDATE treasury_agents SET enabled=0 WHERE network=? AND asset=?",
                (network, asset.upper()),
            )
            db.commit()

    def open_reorg_alerts(self, *, network: str, asset: str) -> int:
        with closing(self.store._connect()) as db:
            row = db.execute(
                """SELECT COUNT(*) AS n FROM treasury_reorg_alerts
                   WHERE network=? AND asset=? AND status='open'""",
                (network, asset.upper()),
            ).fetchone()
        return int(row["n"])

    def resolve_reorg_alert(self, *, network: str, asset: str,
                            tx_hash: str, transfer_ref: str,
                            operator_note: str) -> None:
        """Record an explicit operator resolution; never resumes agent spending."""
        if not isinstance(operator_note, str) or len(operator_note.strip()) < 12:
            raise ValueError("operator_note must explain the resolution (at least 12 characters)")
        with closing(self.store._connect()) as db:
            cur = db.execute(
                """UPDATE treasury_reorg_alerts SET status='resolved',
                   resolved_at=CURRENT_TIMESTAMP,reason=reason || ' | RESOLVED: ' || ?
                   WHERE network=? AND asset=? AND tx_hash=? AND transfer_ref=?
                     AND status='open'""",
                (operator_note.strip(), network, asset.upper(), tx_hash, transfer_ref),
            )
            if cur.rowcount != 1:
                raise ValueError("open treasury reorganization alert not found")

    def resume_agent_after_review(self, *, agent_id: str,
                                  network: str, asset: str) -> None:
        """Explicitly resume one agent only after every pool alert is resolved."""
        with closing(self.store._connect()) as db:
            open_alerts = db.execute(
                """SELECT COUNT(*) AS n FROM treasury_reorg_alerts
                   WHERE network=? AND asset=? AND status='open'""",
                (network, asset.upper()),
            ).fetchone()["n"]
            if open_alerts:
                raise ValueError("cannot resume agent while treasury reorganization alerts remain open")
            cur = db.execute(
                """UPDATE treasury_agents SET enabled=1
                   WHERE agent_id=? AND network=? AND asset=?""",
                (agent_id, network, asset.upper()),
            )
            if cur.rowcount != 1:
                raise ValueError("agent treasury policy not found")

    def bind_payer(self, attribution_ref: str, payer_address: str) -> None:
        """Bind an intent to the expected payer before publishing payment details."""
        if not isinstance(attribution_ref, str) or not attribution_ref.strip():
            raise ValueError("attribution_ref is required")
        if not isinstance(payer_address, str) or not _ADDRESS.fullmatch(payer_address):
            raise ValueError("payer_address must be a valid EVM address")
        with closing(self.store._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            intent = db.execute(
                "SELECT status FROM treasury_payment_intents WHERE attribution_ref=?",
                (attribution_ref,),
            ).fetchone()
            if not intent or intent["status"] != "pending":
                db.rollback()
                raise ValueError("payer can only be bound to a pending payment intent")
            old = db.execute(
                "SELECT payer_address FROM treasury_payer_bindings WHERE attribution_ref=?",
                (attribution_ref,),
            ).fetchone()
            if old:
                if old["payer_address"].lower() != payer_address.lower():
                    db.rollback()
                    raise ValueError("payment intent is already bound to another payer")
                db.commit()
                return
            db.execute(
                "INSERT INTO treasury_payer_bindings(attribution_ref,payer_address) VALUES(?,?)",
                (attribution_ref, payer_address),
            )
            db.commit()

    def _matching_intent(self, item: ChainTransferObservation) -> tuple[str, str] | None:
        with closing(self.store._connect()) as db:
            rows = db.execute(
                """SELECT i.attribution_ref,i.agent_id
                   FROM treasury_payment_intents i
                   JOIN treasury_payer_bindings p USING(attribution_ref)
                   WHERE i.status='pending' AND i.network=? AND i.asset=?
                     AND i.expected_amount_minor=? AND lower(p.payer_address)=lower(?)""",
                (item.network, item.asset.upper(), item.amount_minor, item.source),
            ).fetchall()
        # Never guess when a payer has multiple identical pending invoices.
        return (rows[0]["agent_id"], rows[0]["attribution_ref"]) if len(rows) == 1 else None

    @staticmethod
    def _verified_transfer(item: ChainTransferObservation) -> VerifiedTransfer:
        if not item.canonical or not item.finalized or item.confirmations < 1:
            raise ValueError("incoming transfer is not canonical and finalized")
        if not isinstance(item.block_timestamp, str):
            raise ValueError("block timestamp is required")
        parsed = datetime.fromisoformat(item.block_timestamp.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("block timestamp must include a timezone")
        return VerifiedTransfer(
            item.network, item.asset.upper(), item.tx_hash, item.transfer_ref,
            item.destination, item.amount_minor, item.confirmations, True,
            source=item.source,
        )

    def poll_once(self, *, network: str, asset: str, period_id: str) -> dict:
        wallet = self.store.treasury_wallet(network, asset)
        if not wallet:
            raise ValueError("collective treasury wallet is not registered")
        if not isinstance(period_id, str) or not period_id.strip():
            raise ValueError("period_id is required")
        with closing(self.store._connect()) as db:
            row = db.execute(
                """SELECT cursor FROM treasury_receipt_monitor_cursors
                   WHERE network=? AND asset=? AND token_contract=?""",
                (network, asset.upper(), self.token_contract),
            ).fetchone()
        cursor = row["cursor"] if row else None
        page = self.source.fetch_transfers(
            network=network, token_contract=self.token_contract,
            addresses=(wallet.address,), cursor=cursor,
        )
        if not isinstance(page, TransferPage):
            raise ValueError("receipt source returned an invalid page")
        counts = {"fetched": len(page.transfers), "allocated": 0,
                  "unallocated": 0, "pending": 0, "orphaned": 0}
        for item in page.transfers:
            if not isinstance(item, ChainTransferObservation):
                raise ValueError("receipt source returned an invalid observation")
            if (not isinstance(item.network, str) or not isinstance(item.asset, str)
                    or not isinstance(item.token_contract, str)
                    or not isinstance(item.destination, str)
                    or not isinstance(item.source, str)
                    or not isinstance(item.tx_hash, str)
                    or not isinstance(item.transfer_ref, str)
                    or not isinstance(item.block_hash, str)):
                raise ValueError("observation contains invalid identity fields")
            if (item.network != network or item.asset.upper() != asset.upper()
                    or item.token_contract.lower() != self.token_contract.lower()
                    or item.destination.lower() != wallet.address.lower()):
                raise ValueError("observation does not match the configured treasury")
            if (not _ADDRESS.fullmatch(item.source) or not _ADDRESS.fullmatch(item.destination)
                    or not re.fullmatch(r"0x[0-9a-fA-F]{64}", item.tx_hash)
                    or not re.fullmatch(r"0x[0-9a-fA-F]{64}", item.block_hash)
                    or not item.transfer_ref.startswith("log:")
                    or not item.transfer_ref[4:].isdigit()
                    or isinstance(item.amount_minor, bool) or not isinstance(item.amount_minor, int)
                    or item.amount_minor <= 0
                    or isinstance(item.confirmations, bool) or not isinstance(item.confirmations, int)
                    or item.confirmations < 0
                    or isinstance(item.block_number, bool) or not isinstance(item.block_number, int)
                    or item.block_number < 0
                    or not isinstance(item.canonical, bool)
                    or not isinstance(item.finalized, bool)):
                raise ValueError("observation has malformed transfer fields")
            if not item.canonical:
                with closing(self.store._connect()) as db:
                    prior = db.execute(
                        """SELECT block_hash,block_number,status FROM treasury_receipt_monitor_events
                           WHERE network=? AND tx_hash=? AND transfer_ref=?""",
                        (network, item.tx_hash, item.transfer_ref),
                    ).fetchone()
                if prior and prior["status"] in {"allocated", "unallocated"}:
                    self._raise_reorg_alert(
                        network=network, asset=asset, tx_hash=item.tx_hash,
                        transfer_ref=item.transfer_ref,
                        expected_block_hash=prior["block_hash"],
                        observed_block_hash=item.block_hash,
                        reason="previously credited transfer is no longer canonical",
                    )
                    counts["orphaned"] += 1
                    continue
                counts["orphaned"] += 1
                continue
            if not item.finalized or item.confirmations < 1:
                counts["pending"] += 1
                continue
            with closing(self.store._connect()) as db:
                prior_event = db.execute(
                    """SELECT block_hash,status FROM treasury_receipt_monitor_events
                       WHERE network=? AND tx_hash=? AND transfer_ref=?""",
                    (network, item.tx_hash, item.transfer_ref),
                ).fetchone()
            if prior_event:
                if (prior_event["block_hash"].lower() != item.block_hash.lower()
                        or prior_event["block_number"] != item.block_number):
                    self._raise_reorg_alert(
                        network=network, asset=asset, tx_hash=item.tx_hash,
                        transfer_ref=item.transfer_ref,
                        expected_block_hash=prior_event["block_hash"],
                        observed_block_hash=item.block_hash,
                        reason="previously ingested transfer appeared in a different block",
                    )
                    raise ValueError(
                        "treasury reorganization alert opened; agent spending paused "
                        "until operator reconciliation"
                    )
                if prior_event["status"] in {"allocated", "unallocated"}:
                    counts[prior_event["status"]] += 1
                    continue
            # Persist the observed block identity before the ledger write. If the
            # process crashes after the ledger commit, replay can verify this hash.
            with closing(self.store._connect()) as db:
                db.execute(
                    """INSERT INTO treasury_receipt_monitor_events
                       (network,tx_hash,transfer_ref,block_hash,block_number,status)
                       VALUES(?,?,?,?,?,'pending')
                       ON CONFLICT(network,tx_hash,transfer_ref) DO NOTHING""",
                    (network, item.tx_hash, item.transfer_ref, item.block_hash, item.block_number),
                )
            event_period = self.period_resolver(item.block_timestamp) if self.period_resolver else period_id
            if not isinstance(event_period, str) or not event_period.strip():
                raise ValueError("period resolver returned an invalid period")
            transfer = self._verified_transfer(item)
            with closing(self.store._connect()) as db:
                old_receipt = db.execute(
                    """SELECT source_address,destination_address,amount_minor,status
                       FROM treasury_receipts WHERE network=? AND asset=?
                         AND tx_hash=? AND transfer_ref=?""",
                    (network, asset.upper(), item.tx_hash, item.transfer_ref),
                ).fetchone()
            if old_receipt:
                if (old_receipt["source_address"].lower() != item.source.lower()
                        or old_receipt["destination_address"].lower() != item.destination.lower()
                        or old_receipt["amount_minor"] != item.amount_minor):
                    raise ValueError("replayed receipt conflicts with the existing ledger record")
                result = old_receipt["status"]
            else:
                match = self._matching_intent(item)
                agent_id, attribution_ref = match if match else (None, None)
                result = self.store.record_receipt(
                    transfer, period_id=event_period,
                    agent_id=agent_id, attribution_ref=attribution_ref,
                )
            with closing(self.store._connect()) as db:
                db.execute(
                    """UPDATE treasury_receipt_monitor_events
                       SET status=?,updated_at=CURRENT_TIMESTAMP
                       WHERE network=? AND tx_hash=? AND transfer_ref=? AND block_hash=?""",
                    (result, network, item.tx_hash, item.transfer_ref, item.block_hash),
                )
            counts[result] += 1
        # Advance only after the whole page is ingested; failed pages replay safely.
        with closing(self.store._connect()) as db:
            db.execute(
                """INSERT INTO treasury_receipt_monitor_cursors
                   (network,asset,token_contract,cursor) VALUES(?,?,?,?)
                   ON CONFLICT(network,asset,token_contract) DO UPDATE SET
                   cursor=excluded.cursor,updated_at=CURRENT_TIMESTAMP""",
                (network, asset.upper(), self.token_contract, page.next_cursor),
            )
        return {**counts, "next_cursor": page.next_cursor}


__all__ = ["CollectiveTreasuryReceiptMonitor", "QuorumTreasuryReceiptSource", "TreasuryReceiptSource"]
