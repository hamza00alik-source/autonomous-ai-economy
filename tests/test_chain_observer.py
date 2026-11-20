import tempfile
import unittest
from pathlib import Path

from economy.chain_observer import (
    ChainObserverError,
    ReadOnlyEVMTransferObserver,
    TransferExpectation,
)

CHAIN_ID = 11155111
TOKEN = "0x" + "1" * 40
RECIPIENT = "0x" + "2" * 40
TX_HASH = "0x" + "a" * 64
BLOCK_HASH = "0x" + "b" * 64
AMOUNT = 1234567
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"


def topic_address(address):
    return "0x" + ("0" * 24) + address[2:].lower()


def uint256_word(value):
    """Encode an unsigned integer as a 32-byte ABI word."""
    return "0x" + format(value, "064x")


class FakeRPC:
    def __init__(self):
        self.chain_id = hex(CHAIN_ID)
        self.latest = hex(120)
        self.status = "0x1"
        self.block_hash = BLOCK_HASH
        self.receipt_available = True
        self.logs = [{
            "address": TOKEN,
            "topics": [
                TRANSFER_TOPIC,
                topic_address("0x" + "3" * 40),
                topic_address(RECIPIENT),
            ],
            "data": uint256_word(AMOUNT),
            "logIndex": "0x2",
        }]
        self.methods = []

    def __call__(self, method, params):
        self.methods.append(method)
        if method == "eth_chainId":
            return self.chain_id
        if method == "eth_getTransactionReceipt":
            if not self.receipt_available:
                return None
            return {
                "transactionHash": TX_HASH,
                "status": self.status,
                "blockNumber": "0x64",
                "blockHash": BLOCK_HASH,
                "logs": self.logs,
            }
        if method == "eth_blockNumber":
            return self.latest
        if method == "eth_getBlockByNumber":
            return {"hash": self.block_hash}
        raise AssertionError(f"unexpected RPC method: {method}")


class ReadOnlyEVMTransferObserverTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.rpc = FakeRPC()
        self.observer = ReadOnlyEVMTransferObserver(
            self.rpc, Path(self.tmp.name) / "observed.sqlite3", CHAIN_ID
        )
        self.expected = TransferExpectation(
            chain_id=CHAIN_ID,
            token_contract=TOKEN,
            recipient=RECIPIENT,
            amount_raw=AMOUNT,
            min_confirmations=12,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_verifies_confirmed_transfer_and_returns_raw_amount(self):
        result = self.observer.verify_transfer(TX_HASH, self.expected)
        self.assertEqual(result.amount_raw, AMOUNT)
        self.assertEqual(result.confirmations, 21)
        self.assertEqual(result.log_index, 2)

    def test_only_uses_read_only_rpc_methods(self):
        self.observer.verify_transfer(TX_HASH, self.expected)
        self.assertTrue(set(self.rpc.methods).issubset({
            "eth_chainId", "eth_getTransactionReceipt",
            "eth_blockNumber", "eth_getBlockByNumber",
        }))

    def test_rejects_wrong_rpc_chain(self):
        self.rpc.chain_id = hex(1)
        with self.assertRaises(ChainObserverError):
            self.observer.verify_transfer(TX_HASH, self.expected)

    def test_rejects_failed_transaction(self):
        self.rpc.status = "0x0"
        with self.assertRaises(ChainObserverError):
            self.observer.verify_transfer(TX_HASH, self.expected)

    def test_rejects_unavailable_receipt(self):
        self.rpc.receipt_available = False
        with self.assertRaises(ChainObserverError):
            self.observer.verify_transfer(TX_HASH, self.expected)

    def test_rejects_insufficient_confirmations(self):
        self.rpc.latest = "0x64"
        with self.assertRaises(ChainObserverError):
            self.observer.verify_transfer(TX_HASH, self.expected)

    def test_rejects_noncanonical_block(self):
        self.rpc.block_hash = "0x" + "c" * 64
        with self.assertRaises(ChainObserverError):
            self.observer.verify_transfer(TX_HASH, self.expected)

    def test_rejects_wrong_amount(self):
        self.rpc.logs[0]["data"] = uint256_word(AMOUNT + 1)
        with self.assertRaises(ChainObserverError):
            self.observer.verify_transfer(TX_HASH, self.expected)

    def test_rejects_wrong_token_contract(self):
        self.rpc.logs[0]["address"] = "0x" + "4" * 40
        with self.assertRaises(ChainObserverError):
            self.observer.verify_transfer(TX_HASH, self.expected)

    def test_rejects_multiple_matching_transfer_logs(self):
        duplicate = dict(self.rpc.logs[0])
        duplicate["logIndex"] = "0x3"
        self.rpc.logs.append(duplicate)
        with self.assertRaises(ChainObserverError):
            self.observer.verify_transfer(TX_HASH, self.expected)

    def test_rejects_duplicate_observation(self):
        self.observer.verify_transfer(TX_HASH, self.expected)
        with self.assertRaises(ChainObserverError):
            self.observer.verify_transfer(TX_HASH, self.expected)

    def test_rejects_invalid_amount_and_hash(self):
        with self.assertRaises(ChainObserverError):
            self.observer.verify_transfer("not-a-hash", self.expected)
        invalid = TransferExpectation(CHAIN_ID, TOKEN, RECIPIENT, 0, 12)
        with self.assertRaises(ChainObserverError):
            self.observer.verify_transfer(TX_HASH, invalid)


if __name__ == "__main__":
    unittest.main()
