import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from economy.builtin_process import SandboxUnavailable, execute_builtin


class BuiltinProcessTests(unittest.TestCase):
    @patch("economy.builtin_process.subprocess.run")
    @patch("economy.builtin_process.shutil.which", return_value="/usr/bin/bwrap")
    def test_executes_allowlisted_agent_inside_bubblewrap(self, _which, run):
        run.return_value = SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"result": "[opportunity research] Find independent evidence"}).encode(),
            stderr=b"",
        )
        result = execute_builtin("opportunity-researcher", "  Find   independent evidence ")
        self.assertIn("Find independent evidence", result)
        command = run.call_args.args[0]
        self.assertIn("--unshare-all", command)
        self.assertIn("--clearenv", command)
        self.assertIn("--ro-bind", command)
        self.assertEqual(run.call_args.kwargs["timeout"], 5)
        self.assertEqual(run.call_args.kwargs["env"], {})

    @patch("economy.builtin_process.shutil.which", return_value=None)
    def test_fails_closed_when_bubblewrap_is_missing(self, _which):
        with self.assertRaisesRegex(SandboxUnavailable, "refusing to execute"):
            execute_builtin("opportunity-researcher", "Do work")

    def test_rejects_agent_outside_fixed_allowlist(self):
        with self.assertRaisesRegex(ValueError, "allowlist"):
            execute_builtin("untrusted-agent", "Do work")

    def test_rejects_oversized_objective_before_spawn(self):
        with self.assertRaisesRegex(ValueError, "4096"):
            execute_builtin("verification-auditor", "x" * 4097)


if __name__ == "__main__":
    unittest.main()
