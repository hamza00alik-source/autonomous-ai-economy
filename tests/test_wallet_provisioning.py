import tempfile
import unittest
from pathlib import Path

from economy.agent_finance import AgentFinanceStore
from economy.wallet_provisioning import (
    ProvisionedWallet, WalletProvisioningStore,
)


class FakeProvisioner:
    def __init__(self):
        self.calls = []
        self.wallets = {}

    def create_wallet(self, *, participant_id, role, network, asset, idempotency_key):
        self.calls.append(idempotency_key)
        if idempotency_key not in self.wallets:
            self.wallets[idempotency_key] = ProvisionedWallet(
                "test-custody", "wallet-" + str(len(self.wallets)),
                network, asset, "0x" + participant_id + role,
            )
        return self.wallets[idempotency_key]


class WalletProvisioningTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.finance = AgentFinanceStore(root / "finance.sqlite3")
        self.store = WalletProvisioningStore(self.finance, root / "provision.sqlite3")
        self.provider = FakeProvisioner()

    def tearDown(self):
        self.tmp.cleanup()

    def test_provisions_distinct_agent_wallet_and_registers_public_address(self):
        wallet = self.store.ensure_wallet(
            "agent-a", "agent", "testnet", "USDC",
            provider_name="test-custody", provisioner=self.provider,
        )
        self.assertEqual(wallet.address, "0xagent-aagent")
        self.assertEqual(self.finance.wallet("agent-a", "agent", "testnet", "USDC"), wallet)
        self.assertEqual(self.store.get("agent-a", "agent", "testnet", "USDC")["status"], "ready")

    def test_repeated_provision_is_idempotent(self):
        first = self.store.ensure_wallet(
            "agent-a", "agent", "testnet", "USDC",
            provider_name="test-custody", provisioner=self.provider,
        )
        second = self.store.ensure_wallet(
            "agent-a", "agent", "testnet", "USDC",
            provider_name="test-custody", provisioner=self.provider,
        )
        self.assertEqual(first, second)
        self.assertEqual(len(self.provider.calls), 1)

    def test_provider_failure_can_be_retried_with_same_key(self):
        class FailsOnce(FakeProvisioner):
            def create_wallet(inner, **kwargs):
                if not inner.calls:
                    inner.calls.append(kwargs["idempotency_key"])
                    raise RuntimeError("temporary provider outage")
                return super(FailsOnce, inner).create_wallet(**kwargs)

        provider = FailsOnce()
        args = ("agent-b", "agent", "testnet", "USDC")
        kwargs = {"provider_name": "test-custody", "provisioner": provider}
        with self.assertRaisesRegex(RuntimeError, "outage"):
            self.store.ensure_wallet(*args, **kwargs)
        wallet = self.store.ensure_wallet(*args, **kwargs)
        self.assertEqual(wallet.address, "0xagent-bagent")
        self.assertEqual(provider.calls[0], provider.calls[1])

    def test_provider_switch_is_rejected(self):
        self.store.ensure_wallet(
            "agent-a", "agent", "testnet", "USDC",
            provider_name="test-custody", provisioner=self.provider,
        )
        with self.assertRaisesRegex(ValueError, "different provider"):
            self.store.ensure_wallet(
                "agent-a", "agent", "testnet", "USDC",
                provider_name="other-provider", provisioner=self.provider,
            )

    def test_provider_network_mismatch_is_rejected(self):
        class WrongNetwork(FakeProvisioner):
            def create_wallet(inner, **kwargs):
                return ProvisionedWallet(
                    "test-custody", "wallet-1", "mainnet", kwargs["asset"], "0xwrong"
                )
        with self.assertRaisesRegex(ValueError, "different network"):
            self.store.ensure_wallet(
                "agent-a", "agent", "testnet", "USDC",
                provider_name="test-custody", provisioner=WrongNetwork(),
            )


if __name__ == "__main__":
    unittest.main()
