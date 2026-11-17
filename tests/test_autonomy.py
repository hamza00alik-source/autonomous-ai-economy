import tempfile
import unittest
from pathlib import Path

from economy.autonomy import AutonomyGate, AutonomyProfile


class AutonomyGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.gate = AutonomyGate(Path(self.tmp.name) / "economy.sqlite3")
        self.profile = AutonomyProfile(
            agent_id="agent-1",
            allowed_actions=frozenset({"discover_demand", "draft_offer", "publish_offer", "accept_order"}),
            currency="USD",
            max_order_value_minor=700,
            daily_order_limit_minor=1000,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_routine_action_does_not_require_per_action_owner_approval(self):
        result = self.gate.authorize(self.profile, "publish_offer")
        self.assertEqual(result["decision"], "allow")

    def test_order_within_limits_is_authorized_and_idempotent(self):
        first = self.gate.authorize(
            self.profile, "accept_order", amount_minor=600,
            currency="USD", idempotency_key="order-1",
        )
        replay = self.gate.authorize(
            self.profile, "accept_order", amount_minor=600,
            currency="USD", idempotency_key="order-1",
        )
        self.assertEqual(first["decision"], "allow")
        self.assertEqual(replay["decision"], "allow")

    def test_daily_limit_is_enforced_across_orders(self):
        self.assertEqual(self.gate.authorize(
            self.profile, "accept_order", amount_minor=600,
            currency="USD", idempotency_key="order-1",
        )["decision"], "allow")
        result = self.gate.authorize(
            self.profile, "accept_order", amount_minor=500,
            currency="USD", idempotency_key="order-2",
        )
        self.assertEqual(result["decision"], "deny")
        self.assertIn("daily", result["reason"])

    def test_high_risk_action_cannot_be_enabled_in_profile(self):
        with self.assertRaisesRegex(ValueError, "high-risk"):
            AutonomyProfile(
                agent_id="agent-1", allowed_actions=frozenset({"transfer"}),
                currency="USD", max_order_value_minor=0,
                daily_order_limit_minor=0,
            )

    def test_unknown_action_and_disabled_profile_fail_closed(self):
        self.assertEqual(self.gate.authorize(self.profile, "delete_account")["decision"], "deny")
        disabled = AutonomyProfile(
            agent_id="agent-2", allowed_actions=frozenset({"publish_offer"}),
            currency="USD", max_order_value_minor=0,
            daily_order_limit_minor=0, enabled=False,
        )
        self.assertEqual(self.gate.authorize(disabled, "publish_offer")["decision"], "deny")

    def test_idempotency_key_cannot_change_order_terms(self):
        self.gate.authorize(
            self.profile, "accept_order", amount_minor=200,
            currency="USD", idempotency_key="same-key",
        )
        result = self.gate.authorize(
            self.profile, "accept_order", amount_minor=300,
            currency="USD", idempotency_key="same-key",
        )
        self.assertEqual(result["decision"], "deny")


if __name__ == "__main__":
    unittest.main()
