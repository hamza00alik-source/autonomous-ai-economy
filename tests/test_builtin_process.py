import json
import shutil
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from economy.builtin_process import SandboxUnavailable, execute_builtin, _apply_process_limits


class BuiltinProcessTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("bwrap"), "bubblewrap is not installed on this host")
    def test_real_bubblewrap_namespace_smoke(self):
        result = execute_builtin("verification-auditor", "Check source evidence")
        self.assertIn("Check source evidence", result)

    @patch("economy.builtin_process.resource.setrlimit")
    def test_sets_inherited_cpu_memory_file_and_descriptor_limits(self, setrlimit):
        _apply_process_limits()
        limits = {call.args[0]: call.args[1] for call in setrlimit.call_args_list}
        self.assertEqual(limits[2], (3, 3))
        self.assertEqual(limits[9], (512 * 1024 * 1024, 512 * 1024 * 1024))
        self.assertEqual(limits[1], (1024 * 1024, 1024 * 1024))
        self.assertEqual(limits[7], (32, 32))
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
        self.assertIn("--cap-drop", command)
        self.assertIn("--uid", command)
        self.assertIn("65534", command)
        self.assertIn("--gid", command)
        self.assertIn("ALL", command)
        self.assertIn("--clearenv", command)
        self.assertIn("--ro-bind", command)
        self.assertEqual(run.call_args.kwargs["timeout"], 5)
        self.assertEqual(run.call_args.kwargs["env"], {})
        self.assertIsNotNone(run.call_args.kwargs["preexec_fn"])

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
