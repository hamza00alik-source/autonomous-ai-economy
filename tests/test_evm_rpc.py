import unittest

from economy.evm_rpc import EVMJSONRPCSource, EVMRPCConfig, EVMRPCError, TRANSFER_TOPIC


TOKEN = "0x" + "1" * 40
AGENT = "0x" + "a" * 40
CUSTOMER = "0x" + "b" * 40
TX = "0x" + "c" * 64
BLOCK = "0x" + "d" * 64


def topic(address):
    return "0x" + ("0" * 24) + address[2:].lower()


def rpc_log(**overrides):
    result = {
        "address": TOKEN,
        "topics": [TRANSFER_TOPIC, topic(CUSTOMER), topic(AGENT)],
        "data": hex(123456),
        "blockNumber": "0x64",
        "blockHash": BLOCK,
        "transactionHash": TX,
        "logIndex": "0x2",
        "removed": False,
    }
    result.update(overrides)
    return result


class FakeRPC:
    def __init__(self, logs=None, chain_id="0x539"):
        self.logs = logs or []
        self.chain_id = chain_id
        self.calls = []

    def __call__(self, method, params):
        self.calls.append((method, params))
        if method == "eth_chainId":
            return self.chain_id
        if method == "eth_getBlockByNumber":
            tag = params[0]
            if tag == "latest":
                number = 110
            elif tag == "finalized":
                number = 105
            else:
                number = int(tag, 16)
            return {
                "number": hex(number),
                "hash": BLOCK,
                "timestamp": hex(1795090000),
            }
        if method == "eth_getLogs":
            return self.logs
        raise AssertionError(method)


class EVMRPCSourceTests(unittest.TestCase):
    def setUp(self):
        self.config = EVMRPCConfig(
            rpc_url="https://rpc.example.invalid", network="evm-testnet",
            chain_id=1337, asset="USDC", token_contract=TOKEN,
            start_block=90, max_block_range=20,
        )

    def test_decodes_finalized_transfer_and_paginates(self):
        rpc = FakeRPC([rpc_log()])
        source = EVMJSONRPCSource(self.config, rpc_call=rpc)
        page = source.fetch_transfers(
            network="evm-testnet", token_contract=TOKEN,
            addresses=(AGENT,), cursor=None,
        )
        self.assertEqual(len(page.transfers), 1)
        item = page.transfers[0]
        self.assertEqual(item.source, CUSTOMER)
        self.assertEqual(item.destination, AGENT)
        self.assertEqual(item.amount_minor, 123456)
        self.assertEqual(item.transfer_ref, "log:2")
        self.assertEqual(item.confirmations, 11)
        self.assertTrue(item.canonical)
        self.assertTrue(item.finalized)
        self.assertEqual(page.next_cursor, "106")
        log_filter = next(params[0] for method, params in rpc.calls if method == "eth_getLogs")
        self.assertEqual(log_filter["fromBlock"], "0x5a")
        self.assertEqual(log_filter["toBlock"], "0x69")

    def test_chain_id_mismatch_fails_closed(self):
        source = EVMJSONRPCSource(self.config, rpc_call=FakeRPC(chain_id="0x1"))
        with self.assertRaisesRegex(EVMRPCError, "chain ID mismatch"):
            source.fetch_transfers(
                network="evm-testnet", token_contract=TOKEN,
                addresses=(AGENT,), cursor=None,
            )

    def test_unfinalized_range_returns_empty_without_querying_logs(self):
        rpc = FakeRPC()
        source = EVMJSONRPCSource(self.config, rpc_call=rpc)
        page = source.fetch_transfers(
            network="evm-testnet", token_contract=TOKEN,
            addresses=(AGENT,), cursor="106",
        )
        self.assertEqual(page.transfers, ())
        self.assertEqual(page.next_cursor, "106")
        self.assertFalse(any(method == "eth_getLogs" for method, _ in rpc.calls))

    def test_rejects_invalid_wallet_address(self):
        source = EVMJSONRPCSource(self.config, rpc_call=FakeRPC())
        with self.assertRaisesRegex(ValueError, "invalid registered"):
            source.fetch_transfers(
                network="evm-testnet", token_contract=TOKEN,
                addresses=("not-an-address",), cursor=None,
            )

    def test_rejects_malformed_log(self):
        source = EVMJSONRPCSource(self.config, rpc_call=FakeRPC([rpc_log(data="0x01")]))
        with self.assertRaisesRegex(EVMRPCError, "amount data"):
            source.fetch_transfers(
                network="evm-testnet", token_contract=TOKEN,
                addresses=(AGENT,), cursor=None,
            )

    def test_removed_log_is_noncanonical(self):
        source = EVMJSONRPCSource(self.config, rpc_call=FakeRPC([rpc_log(removed=True)]))
        page = source.fetch_transfers(
            network="evm-testnet", token_contract=TOKEN,
            addresses=(AGENT,), cursor=None,
        )
        self.assertFalse(page.transfers[0].canonical)


    def test_preserves_registered_checksum_address(self):
        checksummed = "0xAa" + "a" * 38
        rpc = FakeRPC([rpc_log(topics=[TRANSFER_TOPIC, topic(CUSTOMER), topic(checksummed)])])
        source = EVMJSONRPCSource(self.config, rpc_call=rpc)
        page = source.fetch_transfers(
            network="evm-testnet", token_contract=TOKEN,
            addresses=(checksummed,), cursor=None,
        )
        self.assertEqual(page.transfers[0].destination, checksummed)

    def test_finalized_tag_unavailable_fails_closed(self):
        class NoFinalizedRPC(FakeRPC):
            def __call__(self, method, params):
                if method == "eth_getBlockByNumber" and params[0] == "finalized":
                    raise EVMRPCError("finalized tag unsupported")
                return super().__call__(method, params)

        source = EVMJSONRPCSource(self.config, rpc_call=NoFinalizedRPC())
        with self.assertRaisesRegex(EVMRPCError, "finalized tag unsupported"):
            source.fetch_transfers(
                network="evm-testnet", token_contract=TOKEN,
                addresses=(AGENT,), cursor=None,
            )


    def test_reconciles_transfer_against_canonical_receipt(self):
        log = {
            "address": TOKEN,
            "topics": [TRANSFER_TOPIC, topic(CUSTOMER), topic(AGENT)],
            "data": hex(123456),
            "logIndex": "0x2",
            "removed": False,
        }
        class ReceiptRPC(FakeRPC):
            def __call__(self, method, params):
                if method == "eth_getTransactionReceipt":
                    return {"blockNumber": "0x64", "blockHash": BLOCK, "logs": [log]}
                return super().__call__(method, params)
        source = EVMJSONRPCSource(self.config, rpc_call=ReceiptRPC())
        self.assertTrue(source.is_transfer_canonical(
            network="evm-testnet", token_contract=TOKEN, tx_hash=TX,
            transfer_ref="log:2", expected_block_number=100, expected_block_hash=BLOCK,
            source=CUSTOMER, destination=AGENT, amount_minor=123456,
        ))

    def test_missing_receipt_is_noncanonical(self):
        class MissingReceiptRPC(FakeRPC):
            def __call__(self, method, params):
                if method == "eth_getTransactionReceipt":
                    return None
                return super().__call__(method, params)
        source = EVMJSONRPCSource(self.config, rpc_call=MissingReceiptRPC())
        self.assertFalse(source.is_transfer_canonical(
            network="evm-testnet", token_contract=TOKEN, tx_hash=TX,
            transfer_ref="log:2", expected_block_number=100, expected_block_hash=BLOCK,
            source=CUSTOMER, destination=AGENT, amount_minor=123456,
        ))

    def test_changed_block_hash_is_noncanonical(self):
        class ChangedBlockRPC(FakeRPC):
            def __call__(self, method, params):
                if method == "eth_getTransactionReceipt":
                    return {"blockNumber": "0x64", "blockHash": "0x" + "e" * 64, "logs": []}
                return super().__call__(method, params)
        source = EVMJSONRPCSource(self.config, rpc_call=ChangedBlockRPC())
        self.assertFalse(source.is_transfer_canonical(
            network="evm-testnet", token_contract=TOKEN, tx_hash=TX,
            transfer_ref="log:2", expected_block_number=100, expected_block_hash=BLOCK,
            source=CUSTOMER, destination=AGENT, amount_minor=123456,
        ))

    def test_rejects_requested_network_or_token_mismatch(self):
        source = EVMJSONRPCSource(self.config, rpc_call=FakeRPC())
        with self.assertRaisesRegex(ValueError, "network"):
            source.fetch_transfers(
                network="wrong", token_contract=TOKEN, addresses=(AGENT,), cursor=None,
            )
        with self.assertRaisesRegex(ValueError, "token contract"):
            source.fetch_transfers(
                network="evm-testnet", token_contract="0x" + "2" * 40,
                addresses=(AGENT,), cursor=None,
            )


if __name__ == "__main__":
    unittest.main()
