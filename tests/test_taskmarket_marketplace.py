import json
import tempfile
import unittest
from pathlib import Path
from urllib.parse import urlparse

from economy.taskmarket_marketplace import (
    TaskmarketOpportunityStore, TaskmarketPublicTasks, TaskmarketTaskEvaluator,
)


TASK_ID = "0x" + "a" * 64
TX_HASH = "0x" + "b" * 64


def task(**overrides):
    row = {
        "id": TASK_ID, "referenceCode": "TSK-TEST1234", "chainId": 8453,
        "description": "Produce a concise technical report with source links. Deliver the Markdown report and submit it for review. Acceptance requires five verifiable references and accurate calculations.",
        "reward": "5000000", "netReward": "5000000", "escrowTxHash": TX_HASH,
        "escrow": {"tracked": True, "booked": "5000000"},
        "status": "open", "phase": "active", "mode": "bounty",
        "submissionCount": 0, "awardCount": 0,
        "expiryTime": "2030-01-01T00:00:00Z", "submissionWindowOpen": True,
        "stakeRequired": False, "stakeBps": 0, "platformFeeBps": 0,
        "tags": ["research"], "requesterActorType": "agent",
    }
    row.update(overrides)
    return row


class TaskmarketMarketplaceTests(unittest.TestCase):
    def test_search_parses_base_mainnet_tasks_and_reward(self):
        seen = {}
        def fetch(url, timeout):
            seen["url"] = url
            return json.dumps({"tasks": [task(), task("chainId"=4217)]}).encode()
        provider = TaskmarketPublicTasks(fetcher=fetch)
        leads = provider.search(limit=10)
        self.assertEqual(len(leads), 1)
        self.assertEqual(leads[0].reward_usdc, "5.000000")
        self.assertFalse(leads[0].payment_verified)
        self.assertIn("chainId=8453", seen["url"])
        self.assertEqual(urlparse(seen["url"]).hostname, "api.taskmarket.dev")

    def test_rejects_invalid_task_id_and_untrusted_host(self):
        provider = TaskmarketPublicTasks(fetcher=lambda *_: b'{"tasks":[]}')
        with self.assertRaises(ValueError):
            provider.get_task("not-a-task-id")
        with self.assertRaises(ValueError):
            TaskmarketPublicTasks._fetch("https://evil.example/api/tasks", 1)

    def test_get_task_validates_returned_id_and_chain(self):
        provider = TaskmarketPublicTasks(fetcher=lambda *_: json.dumps(task()).encode())
        self.assertEqual(provider.get_task(TASK_ID)["id"], TASK_ID)
        mismatch = TaskmarketPublicTasks(fetcher=lambda *_: json.dumps(task(id="0x" + "c" * 64)).encode())
        with self.assertRaises(ValueError):
            mismatch.get_task(TASK_ID)

    def test_evaluator_qualifies_only_fully_escrow_reported_bounty(self):
        result = TaskmarketTaskEvaluator().evaluate(task(), task())
        self.assertEqual(result["state"], "qualified_for_local_draft")
        self.assertFalse(result["payment_verified"])
        self.assertFalse(result["claim_allowed"])
        self.assertEqual(result["external_actions"], 0)

    def test_evaluator_rejects_split_pool_and_crowded_task(self):
        row = task(description="A bounty: 9 USDC split equally among the passes accepted. Submit a pass.")
        row["submissionCount"] = 80
        result = TaskmarketTaskEvaluator().evaluate(row, row)
        self.assertIn("split_reward_pool", result["reasons"])
        self.assertIn("too_many_competing_submissions", result["reasons"])

    def test_evaluator_rejects_promotional_and_off_platform_payouts(self):
        promo = task(description="Publish one useful public reply. Paid promotion must be disclosed. Submit the permalink.")
        promo_result = TaskmarketTaskEvaluator().evaluate(promo, promo)
        self.assertIn("public_promotion_or_outreach_required", promo_result["reasons"])
        token = task(description="Audit wallets. Payout is FLAPJAX on BSC, paid off-platform. Submit the public report.")
        token_result = TaskmarketTaskEvaluator().evaluate(token, token)
        self.assertIn("off_platform_or_token_payout_terms", token_result["reasons"])

    def test_evaluator_rejects_untracked_escrow_and_worker_stake(self):
        row = task(escrow={"tracked": False, "booked": "5000000"}, stakeRequired=True)
        result = TaskmarketTaskEvaluator().evaluate(row, row)
        self.assertIn("escrow_not_tracked_by_platform", result["reasons"])
        self.assertIn("worker_stake_or_deposit_required", result["reasons"])

    def test_store_persists_evaluations_without_external_actions(self):
        lead = TaskmarketPublicTasks(fetcher=lambda *_: json.dumps({"tasks": [task()]}).encode()).search()[0]
        with tempfile.TemporaryDirectory() as tmp:
            store = TaskmarketOpportunityStore(Path(tmp) / "tasks.sqlite3")
            summary = store.save_many([lead], TaskmarketTaskEvaluator())
            rows = store.list_opportunities()
        self.assertEqual(summary["claims"], 0)
        self.assertEqual(summary["submissions"], 0)
        self.assertEqual(summary["payments"], 0)
        self.assertEqual(rows[0]["evaluation"]["state"], "qualified_for_local_draft")


if __name__ == "__main__":
    unittest.main()
