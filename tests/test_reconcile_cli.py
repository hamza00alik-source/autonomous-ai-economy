import sys
import unittest
from unittest.mock import patch

from economy.cli import main


class ReconcileCLIParserTests(unittest.TestCase):
    def test_reconcile_command_help_is_registered(self):
        with patch.object(sys, "argv", ["economy", "reconcile-chain-once", "--help"]):
            with self.assertRaises(SystemExit) as raised:
                main()
        self.assertEqual(raised.exception.code, 0)


if __name__ == "__main__":
    unittest.main()
