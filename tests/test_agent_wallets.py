import sqlite3
import tempfile
import unittest
from pathlib import Path

from economy.agent_wallets import LocalAgentWalletVault, WalletError


class LocalAgentWalletVaultTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "wallets.sqlite3"
        self.secret = b"test-only-master-secret-material-0123456789abcdef"
        self.vault = LocalAgentWalletVault(self.db_path, self.secret)

    def tearDown(self):
        self.tmp.cleanup()

    def test_creates_valid_evm_address_without_network(self):
        wallet = self.vault.create_wallet("agent-alpha")
        self.assertRegex(wallet.address, r"^0x[0-9a-fA-F]{40}$")
        self.assertEqual(wallet.agent_id, "agent-alpha")
        self.assertEqual(wallet.chain_family, "evm")
        self.assertEqual(self.vault.count(), 1)

    def test_creation_is_idempotent_per_agent(self):
        first = self.vault.create_wallet("agent-alpha")
        second = self.vault.create_wallet("agent-alpha")
        self.assertEqual(first, second)
        self.assertEqual(self.vault.count(), 1)

    def test_agents_receive_distinct_addresses(self):
        first = self.vault.create_wallet("agent-alpha")
        second = self.vault.create_wallet("agent-bravo")
        self.assertNotEqual(first.address, second.address)
        self.assertEqual(self.vault.count(), 2)

    def test_public_record_never_contains_private_key_or_seed(self):
        wallet = self.vault.create_wallet("agent-alpha")
        serialized = repr(wallet).lower()
        for forbidden in ("private_key", "seed_phrase", "mnemonic", "ciphertext"):
            self.assertNotIn(forbidden, serialized)
        self.assertFalse(hasattr(wallet, "private_key"))

    def test_database_stores_ciphertext_not_plaintext_private_key(self):
        self.vault.create_wallet("agent-alpha")
        with sqlite3.connect(self.db_path) as db:
            row = db.execute(
                "SELECT ciphertext, salt, nonce FROM agent_wallets WHERE agent_id=?",
                ("agent-alpha",),
            ).fetchone()
        ciphertext, salt, nonce = row
        self.assertGreater(len(ciphertext), 32)
        self.assertEqual(len(salt), 16)
        self.assertEqual(len(nonce), 12)
        self.assertNotEqual(ciphertext[:32], b"\x00" * 32)

    def test_missing_and_invalid_encryption_secret_rejected(self):
        for secret in (None, b"too-short"):
            with self.subTest(secret=secret):
                with self.assertRaises(WalletError):
                    LocalAgentWalletVault(self.db_path, secret)

    def test_invalid_agent_ids_rejected(self):
        for agent_id in ("", "ab", "bad agent", "../owner", None):
            with self.subTest(agent_id=agent_id):
                with self.assertRaises(WalletError):
                    self.vault.create_wallet(agent_id)

    def test_database_permissions_are_owner_only(self):
        import os
        if os.name == "posix":
            self.vault.create_wallet("agent-alpha")
            self.assertEqual(self.db_path.stat().st_mode & 0o777, 0o600)

    def test_lookup_missing_wallet_returns_none(self):
        self.assertIsNone(self.vault.get_wallet("agent-alpha"))


if __name__ == "__main__":
    unittest.main()
