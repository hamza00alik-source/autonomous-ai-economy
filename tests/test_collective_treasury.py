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
        onchain = self.store.reconcile_onchain_balance("base-sepolia", "USDC", 5500)
        self.assertTrue(onchain["fully_reconciled"])
        mismatch = self.store.reconcile_onchain_balance("base-sepolia", "USDC", 5499)
        self.assertFalse(mismatch["onchain_balanced"])

    def test_spend_policy_and_balance_are_enforced(self):
        self.store.create_payment_intent(
            "agent-a", "base-sepolia", "USDC", 1000, attribution_ref="invoice:policy"
        )
        self.store.record_receipt(
            self.transfer(amount=1000), period_id="2026-11", agent_id="agent-a",
            attribution_ref="invoice:policy",
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

    def test_spend_submission_claim_is_atomic_and_single_use(self):
        self.store.create_payment_intent(
            "agent-a", "base-sepolia", "USDC", 1000, attribution_ref="invoice:claim"
        )
        self.store.record_receipt(
            self.transfer(amount=1000), period_id="2026-11", agent_id="agent-a",
            attribution_ref="invoice:claim",
        )
        reservation = self.store.reserve_spend(
            "agent-a", "base-sepolia", "USDC", "0x" + "b" * 40, 1000,
            idempotency_key="single-claim", period_id="2026-11",
        )
        self.assertTrue(self.store.claim_spend_submission(reservation))
        self.assertFalse(self.store.claim_spend_submission(reservation))

    def test_uncertain_broadcast_is_held_and_not_cancellable(self):
        self.store.create_payment_intent(
            "agent-a", "base-sepolia", "USDC", 8000, attribution_ref="invoice:abc"
        )
        self.store.record_receipt(
            self.transfer(), period_id="2026-11", agent_id="agent-a",
            attribution_ref="invoice:abc",
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
            self.transfer(), period_id="2026-11", agent_id="agent-a",
            attribution_ref="invoice:abc",
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
        self.assertTrue(self.store.reconciliation_snapshot("base-sepolia", "USDC")["balanced"])
        self.assertEqual(self.store.pool_balance("base-sepolia", "USDC"), 8000)
        again = self.store.close_period(
            "agent-a", "base-sepolia", "USDC", "2026-11",
            reserve_bps=1000, owner_share_bps=5000,
        )
        self.assertEqual(result, again)


    def test_profit_close_requires_and_includes_verified_gas_cost_valuation(self):
        self.store.create_payment_intent(
            "agent-a", "base-sepolia", "USDC", 8000, attribution_ref="invoice:gas"
        )
        self.store.record_receipt(
            self.transfer(), period_id="2026-11", agent_id="agent-a",
            attribution_ref="invoice:gas",
        )
        destination = "0x" + "b" * 40
        reservation = self.store.reserve_spend(
            "agent-a", "base-sepolia", "USDC", destination, 1000,
            idempotency_key="agent-a:gas-test", period_id="2026-11",
        )
        tx_hash = "0x" + "2" * 64
        self.store.mark_broadcast(reservation, tx_hash)
        self.store.settle_spend(reservation, VerifiedTransfer(
            "base-sepolia", "USDC", tx_hash, "log:2", destination, 1000,
            12, True, source="0x" + "a" * 40,
        ))
        with self.assertRaisesRegex(ValueError, "gas fee and USDC valuation"):
            self.store.close_period(
                "agent-a", "base-sepolia", "USDC", "2026-11",
                reserve_bps=0, owner_share_bps=5000,
            )
        self.store.record_gas_cost(
            reservation_id=reservation, network="base-sepolia", tx_hash=tx_hash,
            gas_fee_wei=123456789, usdc_cost_minor=200,
            price_source="operator-approved-price-feed",
            price_observed_at="2026-11-19T12:00:00Z",
        )
        result = self.store.close_period(
            "agent-a", "base-sepolia", "USDC", "2026-11",
            reserve_bps=0, owner_share_bps=5000,
        )
        self.assertEqual(result["expenses_minor"], 1200)
        self.assertEqual(result["net_profit_minor"], 6800)
        self.assertEqual(result["owner_share_minor"], 3400)
        # ETH gas is an operating expense, not a USDC pool debit.
        self.assertEqual(self.store.pool_balance("base-sepolia", "USDC"), 7000)


    def test_shared_wallet_has_one_global_500_cap_but_agents_can_earn_more_over_time(self):
        view = self.store.agent_wallet("agent-a", "base-sepolia", "USDC")
        self.assertEqual(view["address"], "0x" + "a" * 40)
        self.assertEqual(view["custody_model"], "shared_treasury")
        self.assertEqual(view["max_balance_usd"], 500)
        self.assertEqual(view["shared_wallet_cap_minor"], 500_000_000)

        # The total wallet capacity is shared by all agents, not duplicated per agent.
        self.store.create_payment_intent(
            "agent-a", "base-sepolia", "USDC", 500_000_000,
            attribution_ref="invoice:cap-full",
        )
        self.store.create_payment_intent(
            "agent-a", "base-sepolia", "USDC", 500_000_000,
            attribution_ref="invoice:cap-full",
        )
        with self.assertRaisesRegex(ValueError, r"shared treasury \$500 total holding cap"):
            self.store.create_payment_intent(
                "agent-b", "base-sepolia", "USDC", 1,
                attribution_ref="invoice:cap-over",
            )
        self.store.record_receipt(
            self.transfer(amount=500_000_000), period_id="2026-11",
            agent_id="agent-a", attribution_ref="invoice:cap-full",
        )
        capacity = self.store.shared_wallet_capacity("base-sepolia", "USDC")
        self.assertEqual(capacity["balance_minor"], 500_000_000)
        self.assertEqual(capacity["remaining_capacity_minor"], 0)
        self.assertFalse(capacity["over_cap"])
        self.assertEqual(
            self.store.agent_wallet("agent-b", "base-sepolia", "USDC")["address"],
            view["address"],
        )

        # Agent A spends $300, then earns another $300. Lifetime earnings are
        # $800, while the shared wallet's current balance remains exactly $500.
        self.store.add_agent(
            "agent-a", "base-sepolia", "USDC",
            daily_limit_minor=1_000_000_000, per_tx_limit_minor=1_000_000_000,
            allowed_destinations=("0x" + "b" * 40, "0x" + "c" * 40),
        )
        reservation = self.store.reserve_spend(
            "agent-a", "base-sepolia", "USDC", "0x" + "b" * 40, 300_000_000,
            idempotency_key="agent-a:spend-300", period_id="2026-11",
        )
        self.store.mark_broadcast(reservation, "0x" + "2" * 64)
        self.store.settle_spend(
            reservation,
            self.transfer(
                tx="0x" + "2" * 64, ref="log:spend", amount=300_000_000,
                source="0x" + "a" * 40, destination="0x" + "b" * 40,
            ),
        )
        self.store.create_payment_intent(
            "agent-a", "base-sepolia", "USDC", 300_000_000,
            attribution_ref="invoice:second-earning",
        )
        self.store.record_receipt(
            self.transfer(tx="0x" + "3" * 64, ref="log:second", amount=300_000_000),
            period_id="2026-11", agent_id="agent-a",
            attribution_ref="invoice:second-earning",
        )
        view = self.store.agent_wallet("agent-a", "base-sepolia", "USDC")
        self.assertEqual(view["balance_minor"], 500_000_000)
        self.assertEqual(view["shared_wallet_balance_minor"], 500_000_000)
        with self.store._connect() as db:
            lifetime_receipts = db.execute(
                """SELECT COALESCE(SUM(amount_minor),0) AS amount FROM treasury_receipts
                   WHERE attributed_agent_id='agent-a'"""
            ).fetchone()["amount"]
        self.assertEqual(lifetime_receipts, 800_000_000)

    def test_unexpected_deposit_overflow_blocks_agent_spending_and_flags_excess(self):
        self.store.create_payment_intent(
            "agent-a", "base-sepolia", "USDC", 400_000_000,
            attribution_ref="invoice:reserved-400",
        )
        # Anyone can send tokens to a public EVM address; an unsolicited
        # deposit may consume capacity that had been reserved for an invoice.
        self.store.record_receipt(
            self.transfer(tx="0x" + "4" * 64, ref="log:unsolicited", amount=200_000_000),
            period_id="2026-11",
        )
        # Do not credit the later invoice to the agent if it would push the
        # pooled on-chain holdings beyond the shared $500 cap.
        result = self.store.record_receipt(
            self.transfer(tx="0x" + "5" * 64, ref="log:reserved", amount=400_000_000),
            period_id="2026-11", agent_id="agent-a",
            attribution_ref="invoice:reserved-400",
        )
        self.assertEqual(result, "unallocated")
        capacity = self.store.shared_wallet_capacity("base-sepolia", "USDC")
        self.assertTrue(capacity["over_cap"])
        self.assertTrue(capacity["spending_blocked"])
        self.assertEqual(capacity["excess_minor"], 100_000_000)
        self.assertEqual(self.store.balance("agent:agent-a", "base-sepolia", "USDC"), 0)
        with self.assertRaisesRegex(ValueError, r"above its configured total holding cap"):
            self.store.reserve_spend(
                "agent-a", "base-sepolia", "USDC", "0x" + "b" * 40, 1,
                idempotency_key="agent-a:blocked-overflow", period_id="2026-11",
            )

    def test_suspense_receipt_can_be_allocated_without_per_agent_earning_cap(self):
        self.store.create_payment_intent(
            "agent-a", "base-sepolia", "USDC", 500_000_000,
            attribution_ref="invoice:suspense-full",
        )
        self.store.record_receipt(
            self.transfer(amount=500_000_000), period_id="2026-11",
            attribution_ref="invoice:suspense-full",
        )
        self.store.attribute_receipt(
            "base-sepolia", "USDC", "0x" + "1" * 64, "log:1", "agent-a",
            expected_attribution_ref="invoice:suspense-full",
        )
        self.assertEqual(
            self.store.balance("agent:agent-a", "base-sepolia", "USDC"),
            500_000_000,
        )
        self.assertEqual(
            self.store.shared_wallet_capacity("base-sepolia", "USDC")["balance_minor"],
            500_000_000,
        )



class CDPAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_transfer_usdc_uses_policy_bound_account_and_atomic_amount(self):
        class Account:
            address = "0x" + "a" * 40
            id = "cdp-id"
            def __init__(self):
                self.transfer_args = None
            async def transfer(self, **kwargs):
                self.transfer_args = kwargs
                return "0x" + "2" * 64

        class EVM:
            def __init__(self):
                self.account = Account()
            async def get_or_create_account(self, **kwargs):
                return self.account
            async def update_account(self, **kwargs):
                return self.account

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
        tx_hash = await adapter.transfer_usdc(
            destination="0x" + "b" * 40, amount_minor=1_250_000,
            network="base-sepolia",
        )
        self.assertEqual(tx_hash, "0x" + "2" * 64)
        self.assertEqual(client.evm.account.transfer_args, {
            "to": "0x" + "b" * 40, "amount": 1_250_000,
            "token": "usdc", "network": "base-sepolia",
        })

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
