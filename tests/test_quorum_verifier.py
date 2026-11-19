import unittest
from types import SimpleNamespace

from economy.evm_rpc import EVMRPCError
from economy.quorum_verifier import QuorumEVMVerifier


class FakeProvider:
    def __init__(self, height=100, canonical=True, error=None):
        self.config = SimpleNamespace(chain_id=84532, network="base-sepolia",
                                      token_contract="0x" + "1" * 40)
        self.height, self.canonical, self.error = height, canonical, error

    def finalized_block_number(self):
        if self.error:
            raise self.error
        return self.height

    def is_transfer_canonical(self, **kwargs):
        if self.error:
            raise self.error
        return self.canonical


class QuorumVerifierTests(unittest.TestCase):
    def test_default_majority_quorum_and_height(self):
        verifier = QuorumEVMVerifier([
            FakeProvider(100), FakeProvider(95), FakeProvider(110),
        ])
        self.assertEqual(verifier.quorum, 2)
        self.assertEqual(verifier.finalized_block_number(), 100)

    def test_majority_true(self):
        verifier = QuorumEVMVerifier([
            FakeProvider(canonical=True), FakeProvider(canonical=True),
            FakeProvider(canonical=False),
        ])
        self.assertTrue(verifier.is_transfer_canonical())

    def test_majority_false(self):
        verifier = QuorumEVMVerifier([
            FakeProvider(canonical=False), FakeProvider(canonical=False),
            FakeProvider(canonical=True),
        ])
        self.assertFalse(verifier.is_transfer_canonical())

    def test_disagreement_fails_closed(self):
        verifier = QuorumEVMVerifier([
            FakeProvider(canonical=True), FakeProvider(canonical=False),
            FakeProvider(error=RuntimeError("provider down")),
        ])
        with self.assertRaises(EVMRPCError):
            verifier.is_transfer_canonical()

    def test_insufficient_finalized_height_providers_fails_closed(self):
        verifier = QuorumEVMVerifier([
            FakeProvider(100), FakeProvider(error=RuntimeError("offline")),
            FakeProvider(error=RuntimeError("offline")),
        ])
        with self.assertRaises(EVMRPCError):
            verifier.finalized_block_number()

    def test_mismatched_chains_rejected(self):
        a, b = FakeProvider(), FakeProvider()
        b.config = SimpleNamespace(chain_id=1, network="mainnet",
                                   token_contract="0x" + "1" * 40)
        with self.assertRaises(ValueError):
            QuorumEVMVerifier([a, b])

    def test_even_provider_count_still_requires_strict_majority(self):
        verifier = QuorumEVMVerifier([
            FakeProvider(canonical=True), FakeProvider(canonical=False),
        ])
        with self.assertRaises(EVMRPCError):
            verifier.is_transfer_canonical()


if __name__ == "__main__":
    unittest.main()
