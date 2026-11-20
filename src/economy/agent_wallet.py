"""Agent-bound interface to the shared AAE treasury wallet.

The LLM/runtime receives only this narrow capability object: public receive
details and a request-spend operation. It never receives a signer or key.
"""
from __future__ import annotations

from typing import Protocol

from .collective_treasury import CollectiveTreasuryStore


class PayerIntentBinder(Protocol):
    def bind_payer(self, attribution_ref: str, payer_address: str) -> None: ...


class AgentTreasuryWallet:
    """A per-agent capability facade over one shared on-chain treasury address."""

    def __init__(
        self,
        store: CollectiveTreasuryStore,
        *,
        agent_id: str,
        network: str,
        asset: str = "USDC",
        receipt_monitor: PayerIntentBinder,
    ) -> None:
        if not all(isinstance(value, str) and value.strip()
                   for value in (agent_id, network, asset)):
            raise ValueError("agent_id, network and asset are required")
        if receipt_monitor is None:
            raise ValueError("a trusted receipt monitor is required")
        self.store = store
        self.agent_id = agent_id
        self.network = network
        self.asset = asset.upper()
        self.receipt_monitor = receipt_monitor

    def wallet(self) -> dict:
        """Return this agent's uncapped virtual balance and shared wallet capacity."""
        return self.store.agent_wallet(self.agent_id, self.network, self.asset)

    def prepare_receive(
        self, amount_minor: int, *, attribution_ref: str, payer_address: str
    ) -> dict:
        """Create an exact amount/payer-bound receive instruction for this agent."""
        if not isinstance(payer_address, str) or not payer_address.strip():
            raise ValueError("payer_address is required")
        self.store.create_payment_intent(
            self.agent_id, self.network, self.asset, amount_minor,
            attribution_ref=attribution_ref,
        )
        self.receipt_monitor.bind_payer(attribution_ref, payer_address)
        view = self.wallet()
        return {
            "agent_id": self.agent_id,
            "network": self.network,
            "asset": self.asset,
            "address": view["address"],
            "expected_amount_minor": amount_minor,
            "attribution_ref": attribution_ref,
            "shared_wallet_cap_minor": view["shared_wallet_cap_minor"],
            "shared_wallet_remaining_minor": view["shared_wallet_remaining_minor"],
            "note": "Send the exact amount from the bound payer address; funds arrive at the shared treasury address and are credited only after finalized verification.",
        }

    def request_spend(
        self,
        destination: str,
        amount_minor: int,
        *,
        idempotency_key: str,
        period_id: str,
    ) -> str:
        """Reserve a policy-compliant spend for the treasury worker to execute."""
        return self.store.reserve_spend(
            self.agent_id, self.network, self.asset, destination, amount_minor,
            idempotency_key=idempotency_key, period_id=period_id,
        )
