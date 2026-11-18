import unittest

from economy.basedagents_claim_readiness import (\n    evaluate_claim_readiness, evaluate_claim_readiness_with_chain_verifier,\n)


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

    def test_chain_verifier_result_is_required_for_owner_review(self):
        class Verifier:
            def verify(self, task, payment):
                return {"verified": True, "status": "verified_base_usdc_deposit"}
        readiness, evidence = evaluate_claim_readiness_with_chain_verifier(
            self.task, self.agent, self.task["payment"], Verifier()
        )
        self.assertEqual(readiness.state, "ready_for_owner_review")
        self.assertTrue(evidence["verified"])
        self.assertFalse(readiness.claim_allowed)

    def test_failed_chain_verifier_keeps_readiness_blocked(self):
        class Verifier:
            def verify(self, task, payment):
                return {"verified": False, "status": "blocked", "reason": "bad_receipt"}
        readiness, evidence = evaluate_claim_readiness_with_chain_verifier(
            self.task, self.agent, self.task["payment"], Verifier()
        )
        self.assertEqual(readiness.state, "blocked")
        self.assertIn("escrow_deposit_not_independently_verified", readiness.reasons)
        self.assertFalse(evidence["verified"])

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

    def test_pending_unverified_payment_flags_do_not_override_funded_chain_proof(self):
        task = {
            **self.task,
            "payment": {"verified": False, "status": "pending"},
        }
        result = evaluate_claim_readiness(task, self.agent, escrow_verified=True)
        self.assertEqual(result.state, "ready_for_owner_review")
        self.assertFalse(result.claim_allowed)

    def test_unfunded_escrow_still_blocks_even_with_registry_payment_flags(self):
        task = {
            **self.task,
            "escrow": {"status": "funding"},
            "payment": {"verified": True},
        }
        result = evaluate_claim_readiness(task, self.agent, escrow_verified=True)
        self.assertIn("escrow_not_funded", result.reasons)
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
