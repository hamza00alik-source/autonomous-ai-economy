import contextlib
import io
import sys
import unittest
from unittest.mock import patch

from economy.cli import main


class MarketplaceCliTests(unittest.TestCase):
    def test_signed_local_marketplace_lifecycle_commands_are_registered(self):
        output = io.StringIO()
        with patch.object(sys, "argv", ["economy", "--help"]), contextlib.redirect_stdout(output):
            with self.assertRaises(SystemExit) as raised:
                main()
        self.assertEqual(raised.exception.code, 0)
        for command in (
            "catalog-draft", "catalog-approval-create", "catalog-publish",
            "task-offer-create", "task-offer-respond", "task-offer-withdraw",
            "receipt-submit-local", "receipt-accept-local",
        ):
            self.assertIn(command, output.getvalue())


if __name__ == "__main__":
    unittest.main()
