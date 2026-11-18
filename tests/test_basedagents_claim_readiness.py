import unittest

from economy.basedagents_claim_readiness import evaluate_claim_readiness


class BasedAgentsClaimReadinessTests(unittest.TestCase):
    def setUp(self):
        self.task = {
            "task_id": "task_123",
            "status": "open",
            "claimable": True,
            "bounty": {
                "amount_display": "5.00 USDC",
                "amount_atomic": "5000000",
                "token": "USDC",
                "network": "eip155:8453",
            },
            "escrow": {
                "status": "funded",
                "deposit_tx_hash": "0x" + "a" * 64,
            },
            "payment": {"verified": True, "status": "pending"},
        }
        self.agent = {
            "agent_id": "ag_example",
            "status": "active",
            "wallet_address": "0x" + "1" * 40,
            "wallet_network": "eip155:8453",
        }

    def test_requires_every_gate_and_still_never_authorizes_claim(self):
        result = evaluate_claim_readiness(
            self.task, self.agent, escrow_verified=True
        )
        self.assertEqual(result.state, "ready_for_owner_review")
        self.assertFalse(result.claim_allowed)

    def test_unverified_escrow_blocks_otherwise_ready_task(self):
        result = evaluate_claim_readiness(self.task, self.agent)
        self.assertEqual(result.state, "blocked")
        self.assertIn("escrow_deposit_not_independently_verified", result.reasons)

    def test_unfunded_or_unverified_registry_payment_blocks(self):
        task = {
            **self.task,
            "escrow": {"status": "funding"},
            "payment": {"verified": False},
        }
        result = evaluate_claim_readiness(task, self.agent, escrow_verified=True)
        self.assertIn("escrow_not_funded", result.reasons)
        self.assertIn("payment_not_verified_by_registry", result.reasons)
        self.assertIn("escrow_deposit_transaction_missing", result.reasons)

    def test_missing_identity_wallet_and_claimability_fail_closed(self):
        task_without_claimability = {
            key: value for key, value in self.task.items() if key != "claimable"
        }
        result = evaluate_claim_readiness(
            task_without_claimability,
            {"status": "pending"},
            escrow_verified=True,
        )
        self.assertIn("claimability_not_explicitly_confirmed", result.reasons)
        self.assertIn("agent_identity_not_registered", result.reasons)
        self.assertIn("valid_payout_wallet_missing", result.reasons)

    def test_wrong_network_and_small_bounty_are_blocked(self):
        task = {
            **self.task,
            "bounty": {
                "amount_display": "0.01",
                "network": "eip155:1",
                "token": "USDC",
            },
        }
        result = evaluate_claim_readiness(task, self.agent, escrow_verified=True)
        self.assertIn("bounty_below_minimum", result.reasons)
        self.assertIn("unsupported_or_missing_payout_network", result.reasons)
        self.assertIn("payout_wallet_network_mismatch", result.reasons)

    def test_non_open_task_is_blocked(self):
        task = {**self.task, "status": "claimed"}
        result = evaluate_claim_readiness(task, self.agent, escrow_verified=True)
        self.assertIn("task_not_open", result.reasons)

    def test_non_usdc_bounty_is_blocked(self):
        task = {
            **self.task,
            "bounty": {**self.task["bounty"], "token": "OTHER"},
        }
        result = evaluate_claim_readiness(task, self.agent, escrow_verified=True)
        self.assertIn("unsupported_bounty_token", result.reasons)


if __name__ == "__main__":
    unittest.main()
