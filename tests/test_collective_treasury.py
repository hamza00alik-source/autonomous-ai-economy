import tempfile
import unittest
from pathlib import Path

from economy.agent_finance import VerifiedTransfer
from economy.collective_treasury import (
    CDPServerTreasuryWallet, CollectiveTreasuryStore, TreasuryWallet,
)


class CollectiveTreasuryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = CollectiveTreasuryStore(Path(self.tmp.name) / "treasury.sqlite3")
        self.store.register_treasury_wallet(TreasuryWallet(
            "coinbase-cdp", "cdp-account-1", "base-sepolia", "USDC", "0x" + "a" * 40
        ))
        self.store.add_agent(
            "agent-a", "base-sepolia", "USDC",
            daily_limit_minor=10_000, per_tx_limit_minor=5_000,
            allowed_destinations=("0x" + "b" * 40, "0x" + "c" * 40),
        )
        self.store.add_agent(
            "agent-b", "base-sepolia", "USDC",
            daily_limit_minor=10_000, per_tx_limit_minor=5_000,
            allowed_destinations=("0x" + "b" * 40,),
        )

    def tearDown(self):
        self.tmp.cleanup()

    def transfer(self, tx="0x" + "1" * 64, ref="log:1", amount=8000,
                 source="0x" + "d" * 40, destination="0x" + "a" * 40,
                 verified=True):
        return VerifiedTransfer(
            "base-sepolia", "USDC", tx, ref, destination, amount, 12, verified,
            source=source,
        )

    def test_one_collective_wallet_is_shared_by_all_agents(self):
        wallet = self.store.treasury_wallet("base-sepolia", "USDC")
        self.assertEqual(wallet.address, "0x" + "a" * 40)
        self.assertEqual(self.store.treasury_wallet("base-sepolia", "USDC"), wallet)
        with self.assertRaisesRegex(ValueError, "different collective"):
            self.store.register_treasury_wallet(TreasuryWallet(
                "other", "other-id", "base-sepolia", "USDC", "0x" + "e" * 40
            ))

    def test_unattributed_receipt_is_held_in_suspense_then_allocated(self):
        self.store.create_payment_intent(
            "agent-a", "base-sepolia", "USDC", 8000, attribution_ref="invoice:abc"
        )
        result = self.store.record_receipt(
            self.transfer(), period_id="2026-11", attribution_ref="invoice:abc"
        )
        self.assertEqual(result, "unallocated")
        self.assertEqual(self.store.balance("treasury:unallocated", "base-sepolia", "USDC"), 8000)
        self.assertEqual(self.store.pool_balance("base-sepolia", "USDC"), 8000)
        self.assertTrue(self.store.reconciliation_snapshot("base-sepolia", "USDC")["balanced"])
        with self.assertRaisesRegex(ValueError, "does not match"):
            self.store.attribute_receipt(
                "base-sepolia", "USDC", "0x" + "1" * 64, "log:1", "agent-a",
                expected_attribution_ref="invoice:wrong",
            )
        self.store.attribute_receipt(
            "base-sepolia", "USDC", "0x" + "1" * 64, "log:1", "agent-a",
            expected_attribution_ref="invoice:abc",
        )
        self.assertEqual(self.store.balance("treasury:unallocated", "base-sepolia", "USDC"), 0)
        self.assertEqual(self.store.balance("agent:agent-a", "base-sepolia", "USDC"), 8000)
        with self.assertRaisesRegex(ValueError, "not found"):
            self.store.attribute_receipt(
                "base-sepolia", "USDC", "0x" + "1" * 64, "log:1", "agent-b",
                expected_attribution_ref="invoice:abc",
            )

    def test_direct_attributed_receipt_and_duplicate_protection(self):
        self.store.create_payment_intent(
            "agent-a", "base-sepolia", "USDC", 8000, attribution_ref="invoice:abc"
        )
        self.store.record_receipt(
            self.transfer(), period_id="2026-11", agent_id="agent-a",
            attribution_ref="invoice:abc",
        )
        self.assertEqual(self.store.balance("agent:agent-a", "base-sepolia", "USDC"), 8000)
        with self.assertRaisesRegex(ValueError, "pending verified payment intent|duplicate"):
            self.store.record_receipt(
                self.transfer(), period_id="2026-11", agent_id="agent-a",
                attribution_ref="invoice:abc",
            )

    def test_agent_can_spend_from_shared_treasury_with_virtual_balance(self):
        self.store.create_payment_intent(
            "agent-a", "base-sepolia", "USDC", 8000, attribution_ref="invoice:abc"
        )
        self.store.record_receipt(
            self.transfer(), period_id="2026-11", agent_id="agent-a",
            attribution_ref="invoice:abc",
        )
        destination = "0x" + "b" * 40
        reservation = self.store.reserve_spend(
            "agent-a", "base-sepolia", "USDC", destination, 2500,
            idempotency_key="agent-a:compute:001", period_id="2026-11",
        )
        self.assertEqual(self.store.balance("agent:agent-a", "base-sepolia", "USDC"), 5500)
        self.assertEqual(self.store.pool_balance("base-sepolia", "USDC"), 8000)
        self.store.mark_broadcast(reservation, "0x" + "2" * 64)
        settled = VerifiedTransfer(
            "base-sepolia", "USDC", "0x" + "2" * 64, "log:2",
            destination, 2500, 12, True, source="0x" + "a" * 40,
        )
        self.store.settle_spend(reservation, settled)
        self.assertEqual(self.store.balance("agent:agent-a", "base-sepolia", "USDC"), 5500)
        snapshot = self.store.reconciliation_snapshot("base-sepolia", "USDC")
        self.assertEqual(snapshot["pool_balance_minor"], 5500)
        self.assertEqual(snapshot["virtual_accounts_total_minor"], 5500)
        self.assertTrue(snapshot["balanced"])

    def test_spend_policy_and_balance_are_enforced(self):
        self.store.record_receipt(
            self.transfer(amount=1000), period_id="2026-11", agent_id="agent-a"
        )
        with self.assertRaisesRegex(ValueError, "allowlisted"):
            self.store.reserve_spend(
                "agent-a", "base-sepolia", "USDC", "0x" + "f" * 40, 100,
                idempotency_key="bad-dest", period_id="2026-11",
            )
        with self.assertRaisesRegex(ValueError, "insufficient"):
            self.store.reserve_spend(
                "agent-a", "base-sepolia", "USDC", "0x" + "b" * 40, 2000,
                idempotency_key="too-much", period_id="2026-11",
            )
        self.store.pause_agent("agent-a", "base-sepolia", "USDC")
        with self.assertRaisesRegex(ValueError, "disabled"):
            self.store.reserve_spend(
                "agent-a", "base-sepolia", "USDC", "0x" + "b" * 40, 100,
                idempotency_key="paused", period_id="2026-11",
            )

    def test_uncertain_broadcast_is_held_and_not_cancellable(self):
        self.store.create_payment_intent(
            "agent-a", "base-sepolia", "USDC", 8000, attribution_ref="invoice:abc"
        )
        self.store.record_receipt(
            self.transfer(), period_id="2026-11", agent_id="agent-a"
        )
        reservation = self.store.reserve_spend(
            "agent-a", "base-sepolia", "USDC", "0x" + "b" * 40, 1000,
            idempotency_key="uncertain", period_id="2026-11",
        )
        self.store.mark_uncertain(reservation)
        with self.assertRaisesRegex(ValueError, "unbroadcast"):
            self.store.cancel_reservation(reservation)
        self.assertEqual(self.store.balance("agent:agent-a", "base-sepolia", "USDC"), 7000)

    def test_payment_intent_must_match_agent_asset_network_and_exact_amount(self):
        self.store.create_payment_intent(
            "agent-a", "base-sepolia", "USDC", 8000, attribution_ref="invoice:exact"
        )
        with self.assertRaisesRegex(ValueError, "does not match"):
            self.store.record_receipt(
                self.transfer(amount=7999, tx="0x" + "3" * 64),
                period_id="2026-11", agent_id="agent-a",
                attribution_ref="invoice:exact",
            )
        with self.assertRaisesRegex(ValueError, "different agent"):
            self.store.record_receipt(
                self.transfer(tx="0x" + "4" * 64), period_id="2026-11",
                agent_id="agent-b", attribution_ref="invoice:exact",
            )

    def test_period_close_refuses_unresolved_spend(self):
        self.store.create_payment_intent(
            "agent-a", "base-sepolia", "USDC", 8000, attribution_ref="invoice:pending-close"
        )
        self.store.record_receipt(
            self.transfer(), period_id="2026-11", agent_id="agent-a",
            attribution_ref="invoice:pending-close",
        )
        self.store.reserve_spend(
            "agent-a", "base-sepolia", "USDC", "0x" + "b" * 40, 1000,
            idempotency_key="close-blocked", period_id="2026-11",
        )
        with self.assertRaisesRegex(ValueError, "unresolved"):
            self.store.close_period(
                "agent-a", "base-sepolia", "USDC", "2026-11",
                reserve_bps=1000, owner_share_bps=5000,
            )

    def test_profit_close_allocates_master_share_and_reserve_once(self):
        self.store.create_payment_intent(
            "agent-a", "base-sepolia", "USDC", 8000, attribution_ref="invoice:abc"
        )
        self.store.record_receipt(
            self.transfer(), period_id="2026-11", agent_id="agent-a"
        )
        result = self.store.close_period(
            "agent-a", "base-sepolia", "USDC", "2026-11",
            reserve_bps=1000, owner_share_bps=5000,
        )
        self.assertEqual(result["net_profit_minor"], 8000)
        self.assertEqual(result["reserve_minor"], 800)
        self.assertEqual(result["owner_share_minor"], 3600)
        self.assertEqual(self.store.balance("master:owner", "base-sepolia", "USDC"), 3600)
        self.assertEqual(self.store.balance("treasury:reserve:agent-a", "base-sepolia", "USDC"), 800)
        again = self.store.close_period(
            "agent-a", "base-sepolia", "USDC", "2026-11",
            reserve_bps=1000, owner_share_bps=5000,
        )
        self.assertEqual(result, again)


class CDPAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_ensure_wallet_uses_one_named_policy_bound_server_account(self):
        class Account:
            address = "0x" + "a" * 40
            id = "cdp-id"

        class EVM:
            def __init__(self):
                self.calls = []
            async def get_or_create_account(self, **kwargs):
                self.calls.append(("get", kwargs))
                return Account()
            async def update_account(self, **kwargs):
                self.calls.append(("update", kwargs))
                return Account()

        class Client:
            def __init__(self):
                self.evm = EVM()
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                return None

        client = Client()
        adapter = CDPServerTreasuryWallet(
            account_policy_id="policy-123", client_factory=lambda: client
        )
        wallet = await adapter.ensure_wallet(network="base-sepolia")
        self.assertEqual(wallet.provider, "coinbase-cdp")
        self.assertEqual(wallet.provider_wallet_id, "cdp-id")
        self.assertEqual(wallet.address, Account.address)
        self.assertEqual(client.evm.calls, [
            ("get", {"name": "AAE_MASTER_TREASURY"}),
            ("update", {"address": Account.address,
                        "update": {"account_policy": "policy-123"}}),
        ])


if __name__ == "__main__":
    unittest.main()
