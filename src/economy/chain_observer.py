"""Read-only EVM ERC-20 transfer observer.

The observer accepts an injected JSON-RPC callable and never signs, broadcasts,
or submits transactions. Amounts are integer token base units (not floats).
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Any


_ADDRESS = re.compile(r"^0x[0-9a-fA-F]{40}$")
_HASH = re.compile(r"^0x[0-9a-fA-F]{64}$")
_TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"


class ChainObserverError(ValueError):
    """The chain response or transfer expectation could not be verified."""


@dataclass(frozen=True)
class TransferExpectation:
    chain_id: int
    token_contract: str
    recipient: str
    amount_raw: int
    min_confirmations: int = 12


@dataclass(frozen=True)
class VerifiedTransfer:
    chain_id: int
    transaction_hash: str
    log_index: int
    token_contract: str
    recipient: str
    amount_raw: int
    block_number: int
    block_hash: str
    confirmations: int


class ReadOnlyEVMTransferObserver:
    """Verify a specific ERC-20 Transfer log against one configured EVM chain.

    rpc_call must be a read-only JSON-RPC transport accepting (method, params).
    This class deliberately has no HTTP client, signer, wallet key, or send method.
    """

    def __init__(
        self,
        rpc_call: Callable[[str, list[Any]], Any],
        database_path: str | Path,
        expected_chain_id: int,
    ):
        if not callable(rpc_call):
            raise ChainObserverError("a read-only RPC callable is required")
        if not isinstance(expected_chain_id, int) or expected_chain_id <= 0:
            raise ChainObserverError("expected chain ID must be a positive integer")
        self._rpc_call = rpc_call
        self.database_path = str(database_path)
        self.expected_chain_id = expected_chain_id
        Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS observed_erc20_transfers (
                    chain_id INTEGER NOT NULL,
                    transaction_hash TEXT NOT NULL,
                    log_index INTEGER NOT NULL,
                    token_contract TEXT NOT NULL,
                    recipient TEXT NOT NULL,
                    amount_raw TEXT NOT NULL,
                    block_number INTEGER NOT NULL,
                    block_hash TEXT NOT NULL,
                    PRIMARY KEY (chain_id, transaction_hash, log_index)
                )
            """)

    def _connect(self):
        db = sqlite3.connect(self.database_path, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    def _rpc(self, method: str, params: list[Any]):
        try:
            return self._rpc_call(method, params)
        except Exception as exc:
            raise ChainObserverError(f"read-only RPC call failed: {method}") from exc

    @staticmethod
    def _hex_int(value: Any, field: str) -> int:
        if not isinstance(value, str) or not value.startswith("0x"):
            raise ChainObserverError(f"invalid {field} in RPC response")
        try:
            return int(value, 16)
        except ValueError as exc:
            raise ChainObserverError(f"invalid {field} in RPC response") from exc

    @staticmethod
    def _address(value: str, field: str) -> str:
        if not isinstance(value, str) or not _ADDRESS.fullmatch(value):
            raise ChainObserverError(f"invalid {field} address")
        return value.lower()

    @staticmethod
    def _topic_address(topic: Any, field: str) -> str:
        if not isinstance(topic, str) or not re.fullmatch(r"0x[0-9a-fA-F]{64}", topic):
            raise ChainObserverError(f"invalid {field} transfer topic")
        return "0x" + topic[-40:].lower()

    def verify_transfer(self, transaction_hash: str, expected: TransferExpectation) -> VerifiedTransfer:
        if not isinstance(expected, TransferExpectation):
            raise ChainObserverError("transfer expectation is required")
        if expected.chain_id != self.expected_chain_id:
            raise ChainObserverError("configured chain ID does not match observer")
        if expected.amount_raw <= 0 or expected.min_confirmations < 1:
            raise ChainObserverError("amount and confirmation threshold must be positive")
        token = self._address(expected.token_contract, "token contract")
        recipient = self._address(expected.recipient, "recipient")
        if not isinstance(transaction_hash, str) or not _HASH.fullmatch(transaction_hash):
            raise ChainObserverError("invalid transaction hash")
        tx_hash = transaction_hash.lower()

        chain_id = self._hex_int(self._rpc("eth_chainId", []), "chain ID")
        if chain_id != self.expected_chain_id:
            raise ChainObserverError("RPC endpoint is connected to the wrong chain")

        receipt = self._rpc("eth_getTransactionReceipt", [tx_hash])
        if not isinstance(receipt, dict):
            raise ChainObserverError("transaction receipt is not available")
        if str(receipt.get("transactionHash", "")).lower() != tx_hash:
            raise ChainObserverError("receipt transaction hash mismatch")
        if self._hex_int(receipt.get("status"), "receipt status") != 1:
            raise ChainObserverError("transaction did not succeed")
        block_number = self._hex_int(receipt.get("blockNumber"), "receipt block number")
        block_hash = receipt.get("blockHash")
        if not isinstance(block_hash, str) or not _HASH.fullmatch(block_hash):
            raise ChainObserverError("invalid receipt block hash")

        matched = []
        logs = receipt.get("logs")
        if not isinstance(logs, list):
            raise ChainObserverError("receipt logs are missing or invalid")
        for log in logs:
            if not isinstance(log, dict):
                continue
            if str(log.get("address", "")).lower() != token:
                continue
            topics = log.get("topics")
            if not isinstance(topics, list) or len(topics) < 3:
                continue
            if str(topics[0]).lower() != _TRANSFER_TOPIC:
                continue
            if self._topic_address(topics[2], "recipient") != recipient:
                continue
            data = log.get("data")
            if not isinstance(data, str) or not re.fullmatch(r"0x[0-9a-fA-F]{64}", data):
                raise ChainObserverError("invalid ERC-20 transfer amount")
            amount = int(data, 16)
            if amount != expected.amount_raw:
                continue
            log_index = self._hex_int(log.get("logIndex"), "log index")
            matched.append((log_index, amount))

        if len(matched) != 1:
            raise ChainObserverError("expected exactly one matching token transfer log")

        latest = self._hex_int(self._rpc("eth_blockNumber", []), "latest block number")
        if latest < block_number:
            raise ChainObserverError("RPC latest block precedes transaction block")
        confirmations = latest - block_number + 1
        if confirmations < expected.min_confirmations:
            raise ChainObserverError("transaction has not reached required finality")

        canonical_block = self._rpc("eth_getBlockByNumber", [hex(block_number), False])
        if not isinstance(canonical_block, dict) or str(canonical_block.get("hash", "")).lower() != block_hash.lower():
            raise ChainObserverError("receipt block is not canonical (possible reorganization)")

        log_index, amount = matched[0]
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                db.execute(
                    """INSERT INTO observed_erc20_transfers
                    (chain_id, transaction_hash, log_index, token_contract,
                     recipient, amount_raw, block_number, block_hash)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (chain_id, tx_hash, log_index, token, recipient, str(amount),
                     block_number, block_hash.lower()),
                )
            except sqlite3.IntegrityError as exc:
                raise ChainObserverError("transfer has already been observed") from exc

        return VerifiedTransfer(
            chain_id=chain_id,
            transaction_hash=tx_hash,
            log_index=log_index,
            token_contract=token,
            recipient=recipient,
            amount_raw=amount,
            block_number=block_number,
            block_hash=block_hash.lower(),
            confirmations=confirmations,
        )
