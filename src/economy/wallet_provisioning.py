"""Provider-neutral, idempotent provisioning of isolated participant wallets.

Only public addresses and provider references are persisted. Custody providers must
implement idempotent creation; this module never handles seeds, private keys or
signatures. A deployment must authenticate/authorize the caller before provisioning.
"""
from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .agent_finance import AgentFinanceStore, Wallet


@dataclass(frozen=True)
class ProvisionedWallet:
    provider: str
    provider_wallet_id: str
    network: str
    asset: str
    address: str


class WalletProvisioner(Protocol):
    """External custody/smart-account adapter; must honor idempotency_key."""

    def create_wallet(self, *, participant_id: str, role: str, network: str,
                      asset: str, idempotency_key: str) -> ProvisionedWallet:
        """Return the same wallet for repeated calls with the same key."""
        ...


class WalletProvisioningStore:
    """Durable provisioning state machine with no key custody."""

    def __init__(self, finance: AgentFinanceStore,
                 path: str | Path = "./data/wallet_provisioning.sqlite3") -> None:
        self.finance = finance
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS wallet_provisioning (
                    participant_id TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('agent','master')),
                    network TEXT NOT NULL,
                    asset TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    provider_wallet_id TEXT,
                    address TEXT,
                    status TEXT NOT NULL CHECK(status IN ('provisioning','ready')),
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY(participant_id, role, network, asset)
                );
            """)

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=15, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=15000")
        return db

    @staticmethod
    def _required(value: str, field: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field} is required")
        return value.strip()

    def get(self, participant_id: str, role: str,
            network: str, asset: str) -> dict | None:
        with closing(self._connect()) as db:
            row = db.execute(
                """SELECT * FROM wallet_provisioning
                   WHERE participant_id=? AND role=? AND network=? AND asset=?""",
                (participant_id, role, network, asset.upper()),
            ).fetchone()
        return dict(row) if row else None

    def ensure_wallet(self, participant_id: str, role: str, network: str,
                      asset: str, *, provider_name: str,
                      provisioner: WalletProvisioner) -> Wallet:
        """Create or recover a participant wallet using one stable provider key.

        Repeated requests are safe only when the provider guarantees idempotency.
        If a process crashes after provider creation, the retry obtains the same
        provider wallet and completes local registration.
        """
        participant_id = self._required(participant_id, "participant_id")
        network = self._required(network, "network")
        asset = self._required(asset, "asset").upper()
        provider_name = self._required(provider_name, "provider_name")
        if role not in {"agent", "master"}:
            raise ValueError("role must be agent or master")
        idempotency_key = f"aae-wallet:{role}:{participant_id}:{network}:{asset}"

        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                """SELECT * FROM wallet_provisioning
                   WHERE participant_id=? AND role=? AND network=? AND asset=?""",
                (participant_id, role, network, asset),
            ).fetchone()
            if row:
                if row["provider"] != provider_name:
                    db.rollback()
                    raise ValueError("wallet is already assigned to a different provider")
                if row["status"] == "ready":
                    db.commit()
                    wallet = Wallet(participant_id, role, network, asset, row["address"])
                    self.finance.register_wallet(wallet)
                    return wallet
            else:
                db.execute(
                    """INSERT INTO wallet_provisioning
                       (participant_id,role,network,asset,provider,idempotency_key,status)
                       VALUES(?,?,?,?,?,?, 'provisioning')""",
                    (participant_id, role, network, asset, provider_name, idempotency_key),
                )
            db.commit()

        # External side effect deliberately occurs outside the SQLite transaction.
        provisioned = provisioner.create_wallet(
            participant_id=participant_id, role=role, network=network,
            asset=asset, idempotency_key=idempotency_key,
        )
        if not isinstance(provisioned, ProvisionedWallet):
            raise ValueError("provider returned an invalid wallet result")
        if provisioned.provider != provider_name:
            raise ValueError("provider identity mismatch")
        if provisioned.network != network or provisioned.asset.upper() != asset:
            raise ValueError("provider returned a wallet for a different network or asset")
        provider_wallet_id = self._required(provisioned.provider_wallet_id, "provider_wallet_id")
        address = self._required(provisioned.address, "address")

        wallet = Wallet(participant_id, role, network, asset, address)
        # Finance registry rejects silent address replacement and address collisions.
        self.finance.register_wallet(wallet)
        with closing(self._connect()) as db:
            db.execute(
                """UPDATE wallet_provisioning
                   SET provider_wallet_id=?, address=?, status='ready',
                       updated_at=CURRENT_TIMESTAMP
                   WHERE participant_id=? AND role=? AND network=? AND asset=?
                     AND provider=? AND idempotency_key=?""",
                (provider_wallet_id, address, participant_id, role, network,
                 asset, provider_name, idempotency_key),
            )
        result = self.get(participant_id, role, network, asset)
        if not result or result["status"] != "ready":
            raise RuntimeError("wallet provisioning did not reach ready state")
        return wallet
