"""Read-only JSON-RPC adapter for ERC-20 Transfer logs on EVM chains.

The adapter never signs or broadcasts transactions. It fails closed when the RPC
endpoint cannot establish the configured chain ID or finalized block height.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable
from urllib.parse import urlparse

from .chain_monitor import ChainTransferObservation, TransferPage


TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
_ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
_HASH_RE = re.compile(r"^0x[0-9a-fA-F]{64}$")


class EVMRPCError(RuntimeError):
    """RPC request failed or returned data that cannot be trusted."""


@dataclass(frozen=True)
class EVMRPCConfig:
    rpc_url: str
    network: str
    chain_id: int
    asset: str
    token_contract: str
    start_block: int
    max_block_range: int = 2_000
    request_timeout: float = 15.0

    def __post_init__(self) -> None:
        parsed = urlparse(self.rpc_url)
        if parsed.scheme not in {"https", "http"} or not parsed.netloc:
            raise ValueError("rpc_url must be an absolute HTTP(S) URL")
        if not self.network.strip() or not self.asset.strip():
            raise ValueError("network and asset are required")
        if isinstance(self.chain_id, bool) or self.chain_id < 1:
            raise ValueError("chain_id must be positive")
        if isinstance(self.start_block, bool) or self.start_block < 0:
            raise ValueError("start_block must be non-negative")
        if isinstance(self.max_block_range, bool) or not 1 <= self.max_block_range <= 100_000:
            raise ValueError("max_block_range must be between 1 and 100000")
        if self.request_timeout <= 0:
            raise ValueError("request_timeout must be positive")
        if not _ADDRESS_RE.fullmatch(self.token_contract):
            raise ValueError("token_contract must be a 20-byte EVM address")


class EVMJSONRPCSource:
    """ChainTransferSource implementation for ERC-20 Transfer events.

    RPC URL and chain/token settings are operator-supplied. The provider is
    read-only from this adapter's perspective. Do not place signing keys here.
    """

    def __init__(self, config: EVMRPCConfig, *,
                 rpc_call: Callable[[str, list], object] | None = None) -> None:
        self.config = config
        self._rpc_call = rpc_call or self._http_rpc_call
        self._request_id = 0

    def _http_rpc_call(self, method: str, params: list) -> object:
        self._request_id += 1
        payload = json.dumps({
            "jsonrpc": "2.0", "id": self._request_id,
            "method": method, "params": params,
        }).encode("utf-8")
        request = urllib.request.Request(
            self.config.rpc_url, data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(
                request, timeout=self.config.request_timeout
            ) as response:
                body = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise EVMRPCError(f"RPC transport failed for {method}") from exc
        if not isinstance(body, dict) or body.get("jsonrpc") != "2.0":
            raise EVMRPCError("RPC returned an invalid JSON-RPC envelope")
        if body.get("error") is not None:
            raise EVMRPCError(f"RPC method {method} failed: {body['error']}")
        if "result" not in body:
            raise EVMRPCError(f"RPC method {method} omitted result")
        return body["result"]

    @staticmethod
    def _quantity(value: object, field: str) -> int:
        if not isinstance(value, str) or not re.fullmatch(r"0x[0-9a-fA-F]+", value):
            raise EVMRPCError(f"RPC returned invalid {field}")
        return int(value, 16)

    @staticmethod
    def _address_topic(address: str) -> str:
        if not isinstance(address, str) or not _ADDRESS_RE.fullmatch(address):
            raise ValueError(f"invalid registered EVM wallet address: {address!r}")
        return "0x" + ("0" * 24) + address[2:].lower()

    def _rpc_block(self, tag: str) -> dict:
        block = self._rpc_call("eth_getBlockByNumber", [tag, False])
        if not isinstance(block, dict):
            raise EVMRPCError(f"RPC could not return block {tag}")
        return block

    def fetch_transfers(self, *, network: str, token_contract: str,
                        addresses: tuple[str, ...], cursor: str | None) -> TransferPage:
        if network != self.config.network:
            raise ValueError("requested network does not match EVM RPC configuration")
        if token_contract.lower() != self.config.token_contract.lower():
            raise ValueError("requested token contract does not match EVM RPC configuration")
        if not addresses:
            return TransferPage((), cursor)
        normalized_addresses = tuple(sorted({self._address_topic(a) for a in addresses}))

        actual_chain_id = self._quantity(self._rpc_call("eth_chainId", []), "chain ID")
        if actual_chain_id != self.config.chain_id:
            raise EVMRPCError(
                f"RPC chain ID mismatch: expected {self.config.chain_id}, got {actual_chain_id}"
            )

        latest = self._rpc_block("latest")
        finalized = self._rpc_block("finalized")
        latest_number = self._quantity(latest.get("number"), "latest block number")
        finalized_number = self._quantity(finalized.get("number"), "finalized block number")
        if finalized_number > latest_number:
            raise EVMRPCError("finalized block is ahead of latest block")

        if cursor is None:
            from_block = self.config.start_block
        else:
            try:
                from_block = int(cursor, 10)
            except (TypeError, ValueError) as exc:
                raise ValueError("cursor must be a decimal block number") from exc
            if from_block < 0:
                raise ValueError("cursor must be non-negative")

        if from_block > finalized_number:
            return TransferPage((), str(from_block))

        to_block = min(finalized_number, from_block + self.config.max_block_range - 1)
        logs = self._rpc_call("eth_getLogs", [{
            "address": self.config.token_contract,
            "fromBlock": hex(from_block),
            "toBlock": hex(to_block),
            "topics": [TRANSFER_TOPIC, None, list(normalized_addresses)],
        }])
        if not isinstance(logs, list):
            raise EVMRPCError("eth_getLogs did not return a list")

        block_cache: dict[int, dict] = {}
        observations: list[ChainTransferObservation] = []
        for log in logs:
            if not isinstance(log, dict):
                raise EVMRPCError("eth_getLogs returned a malformed log")
            topics = log.get("topics")
            if not isinstance(topics, list) or len(topics) != 3:
                raise EVMRPCError("ERC-20 Transfer log must contain exactly three topics")
            if topics[0].lower() != TRANSFER_TOPIC:
                raise EVMRPCError("RPC returned a log with the wrong event signature")
            tx_hash = log.get("transactionHash")
            block_hash = log.get("blockHash")
            if not isinstance(tx_hash, str) or not _HASH_RE.fullmatch(tx_hash):
                raise EVMRPCError("log has invalid transaction hash")
            if not isinstance(block_hash, str) or not _HASH_RE.fullmatch(block_hash):
                raise EVMRPCError("log has invalid block hash")
            source_topic, destination_topic = topics[1], topics[2]
            if (not isinstance(source_topic, str) or not re.fullmatch(r"0x[0-9a-fA-F]{64}", source_topic)
                    or not isinstance(destination_topic, str)
                    or not re.fullmatch(r"0x[0-9a-fA-F]{64}", destination_topic)):
                raise EVMRPCError("log has invalid indexed address topic")
            source = "0x" + source_topic[-40:].lower()
            destination = "0x" + destination_topic[-40:].lower()
            if destination not in {a[-40:] for a in normalized_addresses}:
                raise EVMRPCError("RPC returned a transfer for an unrequested destination")
            data = log.get("data")
            if not isinstance(data, str) or not re.fullmatch(r"0x[0-9a-fA-F]{64}", data):
                raise EVMRPCError("log has invalid uint256 amount data")
            block_number = self._quantity(log.get("blockNumber"), "log block number")
            log_index = self._quantity(log.get("logIndex"), "log index")
            if block_number not in block_cache:
                block = self._rpc_block(hex(block_number))
                block_cache[block_number] = block
            block = block_cache[block_number]
            canonical_hash = block.get("hash")
            if not isinstance(canonical_hash, str) or not _HASH_RE.fullmatch(canonical_hash):
                raise EVMRPCError("RPC block response has invalid hash")
            canonical = canonical_hash.lower() == block_hash.lower() and not bool(log.get("removed", False))
            timestamp = self._quantity(block.get("timestamp"), "block timestamp")
            block_time = datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()
            observations.append(ChainTransferObservation(
                network=self.config.network,
                asset=self.config.asset.upper(),
                token_contract=self.config.token_contract.lower(),
                tx_hash=tx_hash.lower(),
                transfer_ref=f"log:{log_index}",
                source=source,
                destination=destination,
                amount_minor=int(data, 16),
                block_number=block_number,
                block_hash=block_hash.lower(),
                confirmations=max(0, latest_number - block_number + 1),
                canonical=canonical,
                finalized=block_number <= finalized_number,
                block_timestamp=block_time,
            ))

        observations.sort(key=lambda item: (item.block_number, item.tx_hash, item.transfer_ref))
        return TransferPage(tuple(observations), str(to_block + 1))
