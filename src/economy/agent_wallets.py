"""Local, provider-independent EVM wallet creation and encrypted key storage.

This module intentionally creates addresses only. It has no RPC client,
transaction signer, token transfer, export, or withdrawal functionality.
"""
from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes
from eth_account import Account

_AGENT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,79}$")
_KEY_VERSION = 1
_PURPOSE = b"AAE-EVM-AGENT-WALLET:v1:"


class WalletError(ValueError):
    """Wallet creation or storage validation failed."""


@dataclass(frozen=True)
class WalletPublicRecord:
    wallet_id: str
    agent_id: str
    address: str
    chain_family: str
    key_version: int
    fingerprint: str
    created_at: str


class LocalAgentWalletVault:
    """SQLite-backed encrypted key vault; returns public metadata only.

    Supply a unique high-entropy master secret (32+ random bytes) from a
    secret manager/environment. Never commit it or pass it to an AI prompt.
    """

    def __init__(self, database_path: str | Path, master_secret: bytes):
        if not isinstance(master_secret, bytes) or len(master_secret) < 32:
            raise WalletError("wallet encryption secret must contain at least 32 bytes")
        self.database_path = str(database_path)
        self._master_secret = bytes(master_secret)
        Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self):
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self):
        with self._connect() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS agent_wallets (
                    wallet_id TEXT PRIMARY KEY,
                    agent_id TEXT NOT NULL UNIQUE,
                    address TEXT NOT NULL UNIQUE,
                    chain_family TEXT NOT NULL CHECK(chain_family = 'evm'),
                    key_version INTEGER NOT NULL,
                    salt BLOB NOT NULL,
                    nonce BLOB NOT NULL,
                    ciphertext BLOB NOT NULL,
                    fingerprint TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
                )
            """)

    def _encryption_key(self, agent_id: str, salt: bytes) -> bytes:
        return HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            info=_PURPOSE + agent_id.encode("utf-8"),
        ).derive(self._master_secret)

    @staticmethod
    def _public(row) -> WalletPublicRecord:
        return WalletPublicRecord(
            wallet_id=row["wallet_id"],
            agent_id=row["agent_id"],
            address=row["address"],
            chain_family=row["chain_family"],
            key_version=row["key_version"],
            fingerprint=row["fingerprint"],
            created_at=row["created_at"],
        )

    def create_wallet(self, agent_id: str) -> WalletPublicRecord:
        """Create one EVM wallet per agent, idempotently, entirely offline."""
        if not isinstance(agent_id, str) or not _AGENT_ID.fullmatch(agent_id):
            raise WalletError("valid agent ID is required")
        with self._connect() as db:
            existing = db.execute(
                "SELECT * FROM agent_wallets WHERE agent_id = ?", (agent_id,)
            ).fetchone()
            if existing:
                return self._public(existing)

            # Account.create uses cryptographically secure randomness locally.
            account = Account.create()
            private_key = bytes(account.key)
            salt = os.urandom(16)
            nonce = os.urandom(12)
            aad = _PURPOSE + agent_id.encode("utf-8") + b":" + str(_KEY_VERSION).encode()
            ciphertext = AESGCM(self._encryption_key(agent_id, salt)).encrypt(
                nonce, private_key, aad
            )
            fingerprint = hashlib.sha256(bytes.fromhex(account.address[2:])).hexdigest()
            wallet_id = str(uuid.uuid4())
            db.execute(
                """INSERT INTO agent_wallets
                (wallet_id, agent_id, address, chain_family, key_version,
                 salt, nonce, ciphertext, fingerprint)
                VALUES (?, ?, ?, 'evm', ?, ?, ?, ?, ?)""",
                (wallet_id, agent_id, account.address, _KEY_VERSION,
                 salt, nonce, ciphertext, fingerprint),
            )
            row = db.execute(
                "SELECT * FROM agent_wallets WHERE agent_id = ?", (agent_id,)
            ).fetchone()
            return self._public(row)

    def get_wallet(self, agent_id: str) -> WalletPublicRecord | None:
        if not isinstance(agent_id, str) or not _AGENT_ID.fullmatch(agent_id):
            raise WalletError("valid agent ID is required")
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM agent_wallets WHERE agent_id = ?", (agent_id,)
            ).fetchone()
            return self._public(row) if row else None

    def count(self) -> int:
        with self._connect() as db:
            return int(db.execute("SELECT COUNT(*) FROM agent_wallets").fetchone()[0])
