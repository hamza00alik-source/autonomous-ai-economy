import unittest

from economy.basedagents_escrow_verifier import (
    BasedAgentsEscrowVerifier, USDC_BASE, _TRANSFER_TOPIC,
)

TASK_ID = "task_123"
TX = "0x" + "a" * 64
WALLET = "0x0440383B02A10BE0Dea587c5b5Fbb622dBf4719D"
SENDER = "0x" + "1" * 40
AMOUNT = 5_000_000


def topic(address):
    return "0x" + address[2:].lower().rjust(64, "0")


def fixtures():
    task = {
        "task_id": TASK_ID, "status": "open",
        "bounty": {"amount_atomic": str(AMOUNT), "token": "USDC",
                   "network": "eip155:8453"},
        "escrow": {"status": "funded", "wallet": WALLET,
                   "deposit_tx_hash": TX},
    }
    payment = {"task_id": TASK_ID, "verified": True, "status": "funded",
               "deposit_tx_hash": TX}
    config = {
        "payments_enabled": True,
        "escrow": {"enabled": True, "wallet": WALLET},
        "accepts": [{"network": "eip155:8453", "asset": USDC_BASE}],
    }
    receipt = {
        "transactionHash": TX, "status": "0x1",
        "logs": [{
            "address": USDC_BASE,
            "topics": [_TRANSFER_TOPIC, topic(SENDER), topic(WALLET)],
            "data": hex(AMOUNT),
        }],
    }
    return task, payment, config, receipt


class BasedAgentsEscrowVerifierTests(unittest.TestCase):
    def verifier(self, config=None, receipt=None, chain="0x2105"):
        task, payment, default_config, default_receipt = fixtures()
        return BasedAgentsEscrowVerifier(
            get_json=lambda *_: config or default_config,
            rpc=lambda method, *_: {"result": chain if method == "eth_chainId" else receipt or default_receipt},
        )

    def test_exact_live_config_base_usdc_transfer_verifies(self):
        task, payment, *_ = fixtures()
        result = self.verifier().verify(task, payment)
        self.assertTrue(result["verified"])
        self.assertEqual(result["amount_atomic"], str(AMOUNT))

    def test_wrong_chain_blocks(self):
        task, payment, *_ = fixtures()
        result = self.verifier(chain="0x1").verify(task, payment)
        self.assertFalse(result["verified"])
        self.assertEqual(result["reason"], "rpc_endpoint_is_not_base_mainnet")

    def test_failed_transaction_blocks(self):
        task, payment, _, receipt = fixtures()
        receipt["status"] = "0x0"
        result = self.verifier(receipt=receipt).verify(task, payment)
        self.assertEqual(result["reason"], "deposit_transaction_failed")

    def test_wrong_token_recipient_and_amount_block(self):
        task, payment, _, receipt = fixtures()
        for field, value in (("address", "0x" + "2" * 40),
                             ("topics", [_TRANSFER_TOPIC, topic(SENDER), topic(SENDER)]),
                             ("data", hex(AMOUNT + 1))):
            bad = {**receipt, "logs": [{**receipt["logs"][0], field: value}]}
            result = self.verifier(receipt=bad).verify(task, payment)
            self.assertFalse(result["verified"])
            self.assertEqual(result["reason"], "no_exact_usdc_transfer_to_escrow_wallet")

    def test_task_payment_link_mismatch_blocks(self):
        task, payment, *_ = fixtures()
        payment["task_id"] = "another_task"
        result = self.verifier().verify(task, payment)
        self.assertEqual(result["reason"], "payment_task_id_mismatch")

    def test_payment_hash_mismatch_blocks(self):
        task, payment, *_ = fixtures()
        payment["deposit_tx_hash"] = "0x" + "b" * 64
        result = self.verifier().verify(task, payment)
        self.assertEqual(result["reason"], "payment_audit_transaction_mismatch")

    def test_wrong_live_escrow_wallet_blocks(self):
        task, payment, config, _ = fixtures()
        config["escrow"]["wallet"] = "0x" + "2" * 40
        result = self.verifier(config=config).verify(task, payment)
        self.assertEqual(result["reason"], "task_escrow_wallet_differs_from_live_config")

    def test_missing_task_payment_link_blocks(self):
        task, payment, *_ = fixtures()
        payment.pop("task_id")
        result = self.verifier().verify(task, payment)
        self.assertEqual(result["reason"], "payment_task_id_mismatch")

    def test_rpc_url_allowlist(self):
        with self.assertRaises(ValueError):
            BasedAgentsEscrowVerifier(rpc_url="https://example.com")


if __name__ == "__main__":
    unittest.main()
