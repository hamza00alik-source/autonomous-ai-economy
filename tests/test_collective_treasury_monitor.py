import tempfile
import unittest
from pathlib import Path

from economy.chain_monitor import ChainTransferObservation, TransferPage
from economy.collective_treasury import CollectiveTreasuryStore, TreasuryWallet
from economy.collective_treasury_monitor import (
    CollectiveTreasuryReceiptMonitor, QuorumTreasuryReceiptSource,
)


WALLET = "0x" + "a" * 40
PAYER = "0x" + "b" * 40
TOKEN = "0x" + "1" * 40
TX = "0x" + "c" * 64


def observation(*, tx=TX, amount=5000, source=PAYER, finalized=True, canonical=True, block_hash="0x" + "d" * 64):
    return ChainTransferObservation(
        "base-sepolia", "USDC", TOKEN, tx, "log:0", source, WALLET,
        amount, 100, block_hash, 12 if finalized else 1,
        canonical, finalized, "2026-11-19T12:00:00+00:00",
    )


class FakeSource:
    def __init__(self, transfers=()):
        self.transfers = tuple(transfers)
        self.calls = []

    def fetch_transfers(self, **kwargs):
        self.calls.append(kwargs)
        return TransferPage(self.transfers, "120")


class CollectiveTreasuryReceiptMonitorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = CollectiveTreasuryStore(Path(self.tmp.name) / "treasury.sqlite3")
        self.store.register_treasury_wallet(TreasuryWallet(
            "test-provider", "wallet-1", "base-sepolia", "USDC", WALLET
        ))
        self.store.add_agent(
            "agent-a", "base-sepolia", "USDC",
            daily_limit_minor=10000, per_tx_limit_minor=5000,
            allowed_destinations=("0x" + "e" * 40,),
        )
        self.source = FakeSource([observation()])
        self.monitor = CollectiveTreasuryReceiptMonitor(
            self.store, self.source, token_contract=TOKEN
        )

    def tearDown(self):
        self.tmp.cleanup()

    def intent(self, ref="invoice:1", amount=5000):
        self.store.create_payment_intent(
            "agent-a", "base-sepolia", "USDC", amount, attribution_ref=ref
        )

    def test_exact_payer_and_amount_routes_to_agent(self):
        self.intent()
        self.monitor.bind_payer("invoice:1", PAYER)
        result = self.monitor.poll_once(
            network="base-sepolia", asset="USDC", period_id="2026-11"
        )
        self.assertEqual(result["allocated"], 1)
        self.assertEqual(self.store.balance("agent:agent-a", "base-sepolia", "USDC"), 5000)

    def test_unmatched_payer_or_amount_goes_to_suspense(self):
        self.intent()
        self.monitor.bind_payer("invoice:1", "0x" + "f" * 40)
        result = self.monitor.poll_once(
            network="base-sepolia", asset="USDC", period_id="2026-11"
        )
        self.assertEqual(result["unallocated"], 1)
        self.assertEqual(self.store.balance("treasury:unallocated", "base-sepolia", "USDC"), 5000)

    def test_ambiguous_identical_intents_go_to_suspense(self):
        self.intent("invoice:1")
        self.intent("invoice:2")
        self.monitor.bind_payer("invoice:1", PAYER)
        self.monitor.bind_payer("invoice:2", PAYER)
        result = self.monitor.poll_once(
            network="base-sepolia", asset="USDC", period_id="2026-11"
        )
        self.assertEqual(result["unallocated"], 1)
        self.assertEqual(self.store.balance("agent:agent-a", "base-sepolia", "USDC"), 0)

    def test_unfinalized_or_noncanonical_observation_is_not_credited(self):
        self.source.transfers = (observation(finalized=False),)
        pending = self.monitor.poll_once(
            network="base-sepolia", asset="USDC", period_id="2026-11"
        )
        self.assertEqual(pending["pending"], 1)
        self.source.transfers = (observation(tx="0x" + "f" * 64, canonical=False),)
        orphaned = self.monitor.poll_once(
            network="base-sepolia", asset="USDC", period_id="2026-11"
        )
        self.assertEqual(orphaned["orphaned"], 1)
        self.assertEqual(self.store.pool_balance("base-sepolia", "USDC"), 0)

    def test_binding_cannot_be_changed_after_creation(self):
        self.intent()
        self.monitor.bind_payer("invoice:1", PAYER)
        with self.assertRaisesRegex(ValueError, "already bound"):
            self.monitor.bind_payer("invoice:1", "0x" + "f" * 40)

    def test_page_replay_does_not_double_credit(self):
        self.intent()
        self.monitor.bind_payer("invoice:1", PAYER)
        self.monitor.poll_once(network="base-sepolia", asset="USDC", period_id="2026-11")
        result = self.monitor.poll_once(network="base-sepolia", asset="USDC", period_id="2026-11")
        self.assertEqual(result["allocated"], 1)
        self.assertEqual(self.store.pool_balance("base-sepolia", "USDC"), 5000)
        self.assertEqual(self.store.balance("agent:agent-a", "base-sepolia", "USDC"), 5000)

    def test_quorum_cannot_be_lowered_below_strict_majority(self):
        first = FakeSource([observation()])
        second = FakeSource([observation()])
        with self.assertRaisesRegex(ValueError, "strict majority"):
            QuorumTreasuryReceiptSource([first, second], quorum=1)
        with self.assertRaisesRegex(ValueError, "same receipt source"):
            QuorumTreasuryReceiptSource([first, first])

    def test_quorum_source_requires_matching_provider_pages(self):
        page_a = FakeSource([observation()])
        page_b = FakeSource([observation()])
        page_c = FakeSource([observation(tx="0x" + "f" * 64)])
        quorum = QuorumTreasuryReceiptSource([page_a, page_b, page_c], quorum=2)
        result = quorum.fetch_transfers(
            network="base-sepolia", token_contract=TOKEN,
            addresses=(WALLET,), cursor=None,
        )
        self.assertEqual(len(result.transfers), 1)
        self.assertEqual(result.transfers[0].tx_hash, TX)

    def test_quorum_source_fails_closed_without_matching_quorum(self):
        first = FakeSource([observation()])
        second = FakeSource([observation(tx="0x" + "e" * 64)])
        quorum = QuorumTreasuryReceiptSource([first, second], quorum=2)
        with self.assertRaisesRegex(RuntimeError, "providers disagree"):
            quorum.fetch_transfers(
                network="base-sepolia", token_contract=TOKEN,
                addresses=(WALLET,), cursor=None,
            )

    def test_changed_block_identity_fails_closed_after_credit(self):
        self.intent()
        self.monitor.bind_payer("invoice:1", PAYER)
        self.monitor.poll_once(network="base-sepolia", asset="USDC", period_id="2026-11")
        self.source.transfers = (observation(block_hash="0x" + "e" * 64),)
        with self.assertRaisesRegex(ValueError, "changed block identity"):
            self.monitor.poll_once(network="base-sepolia", asset="USDC", period_id="2026-11")
        self.assertEqual(self.store.balance("agent:agent-a", "base-sepolia", "USDC"), 5000)
        with self.assertRaisesRegex(ValueError, "disabled"):
            self.store.reserve_spend(
                "agent-a", "base-sepolia", "USDC", "0x" + "e" * 40, 100,
                idempotency_key="reorg-blocked", period_id="2026-11",
            )

    def test_noncanonical_reappearance_opens_alert_and_pauses_all_agents(self):
        self.intent()
        self.monitor.bind_payer("invoice:1", PAYER)
        self.monitor.poll_once(network="base-sepolia", asset="USDC", period_id="2026-11")
        self.source.transfers = (observation(canonical=False),)
        result = self.monitor.poll_once(
            network="base-sepolia", asset="USDC", period_id="2026-11"
        )
        self.assertEqual(result["orphaned"], 1)
        self.assertEqual(self.monitor.open_reorg_alerts(
            network="base-sepolia", asset="USDC"
        ), 1)
        with self.assertRaisesRegex(ValueError, "disabled"):
            self.store.reserve_spend(
                "agent-a", "base-sepolia", "USDC", "0x" + "e" * 40, 100,
                idempotency_key="reorg-blocked-2", period_id="2026-11",
            )

    def test_operator_resolution_and_resume_are_separate_explicit_actions(self):
        self.intent()
        self.monitor.bind_payer("invoice:1", PAYER)
        self.monitor.poll_once(network="base-sepolia", asset="USDC", period_id="2026-11")
        self.source.transfers = (observation(canonical=False),)
        self.monitor.poll_once(network="base-sepolia", asset="USDC", period_id="2026-11")
        with self.assertRaisesRegex(ValueError, "cannot resume"):
            self.monitor.resume_agent_after_review(
                agent_id="agent-a", network="base-sepolia", asset="USDC"
            )
        with self.assertRaisesRegex(ValueError, "at least 12"):
            self.monitor.resolve_reorg_alert(
                network="base-sepolia", asset="USDC", tx_hash=TX,
                transfer_ref="log:0", operator_note="fixed",
            )
        self.monitor.resolve_reorg_alert(
            network="base-sepolia", asset="USDC", tx_hash=TX,
            transfer_ref="log:0",
            operator_note="Reviewed canonical chain and confirmed original receipt.",
        )
        self.assertEqual(self.monitor.open_reorg_alerts(
            network="base-sepolia", asset="USDC"
        ), 0)
        self.monitor.resume_agent_after_review(
            agent_id="agent-a", network="base-sepolia", asset="USDC"
        )
        self.store.reserve_spend(
            "agent-a", "base-sepolia", "USDC", "0x" + "e" * 40, 100,
            idempotency_key="manually-resumed", period_id="2026-11",
        )


if __name__ == "__main__":
    unittest.main()
