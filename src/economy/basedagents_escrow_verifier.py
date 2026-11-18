"""Independent read-only verifier for BasedAgents' custodial Base USDC deposits.

BasedAgents v1 escrow is a registry house-wallet transfer, not an on-chain
escrow-contract event. This verifier checks the successful Base transaction
receipt for an exact USDC Transfer to the live x402 discovery wallet and
amount. It never signs, sends transactions, or authorizes a claim.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import json
import re
from typing import Any, Callable
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


BASE_CHAIN_ID = "0x2105"  # 8453
BASE_NETWORK = "eip155:8453"
USDC_BASE = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
BASEDAGENTS_API = "api.basedagents.ai"
MAX_RESPONSE_BYTES = 1_000_000
_TX_HASH = re.compile(r"^0x[0-9a-fA-F]{64}$")
_ADDRESS = re.compile(r"^0x[0-9a-fA-F]{40}$")
_TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"


def _address_topic(address: str) -> str:
    if not isinstance(address, str) or not _ADDRESS.fullmatch(address):
        raise ValueError("invalid EVM address")
    return "0x" + address[2:].lower().rjust(64, "0")


def _atomic_amount(task: dict[str, Any]) -> int:
    bounty = task.get("bounty") if isinstance(task.get("bounty"), dict) else {}
    raw = bounty.get("amount_atomic")
    if raw is not None:
        try:
            amount = int(str(raw))
        except (TypeError, ValueError):
            raise ValueError("invalid task bounty atomic amount")
    else:
        display = bounty.get("amount_display")
        try:
            value = Decimal(str(display).replace("USDC", "").strip())
            amount = int(value * Decimal(1_000_000))
            if value * Decimal(1_000_000) != amount:
                raise ValueError("task bounty has fractional atomic units")
        except (InvalidOperation, TypeError, ValueError):
            raise ValueError("missing or invalid task bounty amount")
    if amount <= 0:
        raise ValueError("task bounty amount must be positive")
    return amount


class BasedAgentsEscrowVerifier:
    """Verify task-linked escrow deposits using read-only HTTPS and Base JSON-RPC."""

    def __init__(
        self,
        *,
        rpc_url: str = "https://mainnet.base.org",
        timeout_seconds: float = 12,
        get_json: Callable[[str, float], dict] | None = None,
        rpc: Callable[[str, dict, float], dict] | None = None,
    ):
        if not 1 <= timeout_seconds <= 30:
            raise ValueError("timeout_seconds must be between 1 and 30")
        parsed = urlparse(rpc_url)
        if parsed.scheme != "https" or parsed.hostname not in {
            "mainnet.base.org", "base-rpc.publicnode.com", "base.llamarpc.com"
        }:
            raise ValueError("RPC URL must use an approved HTTPS Base endpoint")
        self.rpc_url = rpc_url
        self.timeout = timeout_seconds
        self._get_json = get_json or self._https_json
        self._rpc = rpc or self._rpc_request

    @staticmethod
    def _https_json(url: str, timeout: float) -> dict:
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname != BASEDAGENTS_API:
            raise ValueError("only HTTPS api.basedagents.ai is allowed for discovery")
        request = Request(url, headers={"Accept": "application/json",
                         "User-Agent": "AutonomousAIEconomy/0.1 escrow-verifier"})
        with urlopen(request, timeout=timeout) as response:
            final = urlparse(response.geturl())
            if final.scheme != "https" or final.hostname != BASEDAGENTS_API:
                raise URLError("discovery response host rejected")
            body = response.read(MAX_RESPONSE_BYTES + 1)
        if len(body) > MAX_RESPONSE_BYTES:
            raise ValueError("discovery response exceeds 1 MB")
        result = json.loads(body)
        if not isinstance(result, dict):
            raise ValueError("unexpected discovery JSON")
        return result

    def _rpc_request(self, method: str, params: dict, timeout: float) -> dict:
        payload = json.dumps({"jsonrpc": "2.0", "id": 1,
                              "method": method, "params": params}).encode()
        request = Request(self.rpc_url, data=payload, method="POST",
                          headers={"Content-Type": "application/json",
                                   "Accept": "application/json"})
        with urlopen(request, timeout=timeout) as response:
            body = response.read(MAX_RESPONSE_BYTES + 1)
        if len(body) > MAX_RESPONSE_BYTES:
            raise ValueError("RPC response exceeds 1 MB")
        result = json.loads(body)
        if not isinstance(result, dict) or result.get("error"):
            raise ValueError("Base RPC returned an error or invalid response")
        return result

    def verify(self, task: dict, payment: dict) -> dict:
        """Return a structured result; all missing/mismatched evidence fails closed."""
        try:
            task_id = task.get("task_id") or task.get("id")
            if not isinstance(task_id, str) or not task_id:
                raise ValueError("missing_task_id")
            if payment.get("task_id") != task_id:
                raise ValueError("payment_task_id_mismatch")
            audit_hashes = []
            for key in ("deposit_tx_hash", "funding_tx_hash"):
                value = payment.get(key)
                if isinstance(value, str):
                    audit_hashes.append(value)
            events = payment.get("events") or payment.get("audit_events") or []
            if isinstance(events, list):
                for event in events:
                    if isinstance(event, dict) and str(event.get("type") or event.get("event") or "").lower() in {
                        "escrow.funded", "escrow_funded", "payment.deposit", "deposit"
                    }:
                        value = event.get("tx_hash") or event.get("transaction_hash")
                        if isinstance(value, str):
                            audit_hashes.append(value)

            escrow = task.get("escrow") if isinstance(task.get("escrow"), dict) else {}
            tx_hash = (escrow.get("deposit_tx_hash") or escrow.get("funding_tx_hash")
                       or payment.get("deposit_tx_hash") or payment.get("funding_tx_hash"))
            if not isinstance(tx_hash, str) or not _TX_HASH.fullmatch(tx_hash):
                raise ValueError("missing_or_invalid_deposit_tx_hash")
            if audit_hashes and any(h.lower() != tx_hash.lower() for h in audit_hashes):
                raise ValueError("payment_audit_transaction_mismatch")
            if payment.get("verified") not in (True, 1):
                raise ValueError("registry_payment_not_verified")
            if payment.get("status") not in ("funded", "pending", "authorized", "settling", "settled"):
                raise ValueError("registry_payment_status_not_funded")

            config = self._get_json("https://api.basedagents.ai/.well-known/x402", self.timeout)
            if config.get("payments_enabled") is not True:
                raise ValueError("payments_not_enabled")
            escrow_config = config.get("escrow")
            if not isinstance(escrow_config, dict) or escrow_config.get("enabled") is not True:
                raise ValueError("escrow_not_enabled")
            recipient = escrow_config.get("wallet")
            if not isinstance(recipient, str) or not _ADDRESS.fullmatch(recipient):
                raise ValueError("invalid_live_escrow_wallet")
            accepts = config.get("accepts")
            matching = [item for item in accepts if isinstance(item, dict)
                        and item.get("network") == BASE_NETWORK
                        and isinstance(item.get("asset"), str)
                        and item.get("asset").lower() == USDC_BASE.lower()] if isinstance(accepts, list) else []
            if not matching:
                raise ValueError("live_config_does_not_advertise_base_usdc")
            bounty = task.get("bounty") if isinstance(task.get("bounty"), dict) else {}
            if bounty.get("network") != BASE_NETWORK:
                raise ValueError("task_bounty_network_is_not_base")
            if bounty.get("token") != "USDC":
                raise ValueError("task_bounty_token_is_not_usdc")
            if task.get("escrow") is False:
                raise ValueError("task_is_not_escrowed")
            if escrow.get("wallet") and escrow["wallet"].lower() != recipient.lower():
                raise ValueError("task_escrow_wallet_differs_from_live_config")
            expected_amount = _atomic_amount(task)

            chain = self._rpc("eth_chainId", {}, self.timeout).get("result")
            if chain != BASE_CHAIN_ID:
                raise ValueError("rpc_endpoint_is_not_base_mainnet")
            response = self._rpc("eth_getTransactionReceipt", {"transactionHash": tx_hash}, self.timeout)
            receipt = response.get("result")
            if not isinstance(receipt, dict):
                raise ValueError("transaction_receipt_not_found")
            if str(receipt.get("transactionHash", "")).lower() != tx_hash.lower():
                raise ValueError("receipt_transaction_hash_mismatch")
            if receipt.get("status") != "0x1":
                raise ValueError("deposit_transaction_failed")
            recipient_topic = _address_topic(recipient)
            matches = []
            for log in receipt.get("logs", []):
                if not isinstance(log, dict) or str(log.get("address", "")).lower() != USDC_BASE.lower():
                    continue
                topics = log.get("topics")
                if not isinstance(topics, list) or len(topics) < 3:
                    continue
                if str(topics[0]).lower() != _TRANSFER_TOPIC:
                    continue
                if str(topics[2]).lower() != recipient_topic:
                    continue
                try:
                    amount = int(str(log.get("data", "0x0")), 16)
                except ValueError:
                    continue
                if amount == expected_amount:
                    matches.append(log)
            if not matches:
                raise ValueError("no_exact_usdc_transfer_to_escrow_wallet")
            return {"verified": True, "status": "verified_base_usdc_deposit",
                    "task_id": task_id, "transaction_hash": tx_hash,
                    "chain_id": 8453, "token": USDC_BASE,
                    "recipient": recipient, "amount_atomic": str(expected_amount),
                    "matching_transfer_logs": len(matches)}
        except (ValueError, TypeError, KeyError, URLError, TimeoutError) as exc:
            reason = str(exc) or "verification_failed"
            return {"verified": False, "status": "blocked", "reason": reason}
